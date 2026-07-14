# Copyright (c) 2024-present, Yumeow. Licensed under the MIT License.
import os
import copy
import heapq
import json
import queue
import shlex
import socket
import sqlite3
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import StringIO
from logging import getLogger
from pathlib import Path
from typing import List

import pandas as pd
import pyotp
import yaml
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.utils.logger import set_logger
from src.utils.ssh_connect import ssh_connect, safe_exec_command

set_logger('ServerMonitor', file='./log/web.log', basename='my')
logger = getLogger('my.web')

# 获取数据文件路径
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = './data'
CONFIG_DIR = Path(os.getenv('CONFIG_DIR', BASE_DIR / 'config'))
TEMPLATE_DIR = BASE_DIR / 'src' / 'web' / 'templates'
ADMIN_SSH_KEY_PATH = os.getenv(
    'ADMIN_SSH_KEY_PATH', '/run/secrets/servermonitor_admin_ssh_key')
with open(CONFIG_DIR / 'hosts.yml', encoding='utf-8') as hosts_file:
    HOSTS = yaml.safe_load(hosts_file) or {}

FILESYSTEM_CACHE_TTL = 20
FILESYSTEM_CACHE = {}
FILESYSTEM_LOCKS = {host: threading.Lock() for host in HOSTS}
DASHBOARD_CACHE_TTL = 10
DASHBOARD_CACHE = {'timestamp': 0.0, 'data': None}
DASHBOARD_CACHE_LOCK = threading.Lock()
VIRTUAL_FILESYSTEM_TYPES = {
    'autofs', 'binfmt_misc', 'cgroup', 'cgroup2', 'configfs', 'debugfs',
    'devpts', 'devtmpfs', 'efivarfs', 'fusectl', 'hugetlbfs', 'mqueue',
    'overlay', 'proc', 'pstore', 'ramfs', 'securityfs', 'squashfs',
    'sysfs', 'tmpfs', 'tracefs', 'fuse.mergerfs',
}
HIDDEN_FILESYSTEM_MOUNTPOINTS = {'/boot', '/boot/efi', '/var/lib/docker'}

HISTORY_IGNORED_USERS = {
    'root', 'www-data', 'nobody', 'messagebus', 'syslog',
    'systemd-timesync', 'earlyoom', 'uuidd', 'colord', 'postfix', '_rpc',
    'postgres', 'systemd-resolve', 'nvidia-persistenced',
    'systemd-network', 'whoopsie', 'kernoops', 'systemd-oom',
    'debian-snmp', 'daemon', 'mas', 'libvirt-dnsmasq', 'rtkit', 'lp',
    'avahi', 'zabbix', 'gdm',
}

# 初始化 FastAPI 实例
app = FastAPI(docs_url=None, redoc_url=None)
app.mount('/css', StaticFiles(directory=TEMPLATE_DIR / 'css'), name='css')
app.mount('/js', StaticFiles(directory=TEMPLATE_DIR / 'js'), name='js')
app.mount('/html', StaticFiles(directory=TEMPLATE_DIR / 'html'), name='html')


def _host_db_paths(host: str, reverse: bool = False):
    """Return this host's (year, database path) pairs."""
    host_dir = os.path.join(DATA_DIR, host)
    if not os.path.isdir(host_dir):
        return []

    paths = []
    for name in os.listdir(host_dir):
        stem, ext = os.path.splitext(name)
        if ext == '.db' and stem.isdigit():
            paths.append((int(stem), os.path.join(host_dir, name)))
    return sorted(paths, reverse=reverse)


def _get_db(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    return conn


def _get_latest_snapshot(host: str):
    for _, db_path in _host_db_paths(host, reverse=True):
        conn = _get_db(db_path)
        try:
            row = conn.execute(
                'SELECT * FROM snapshots WHERE host=? '
                'ORDER BY timestamp DESC LIMIT 1',
                (host,),
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            return row
    return None


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ('gpu_usage_bytes', 'gpu_total_bytes',
                'cpu_per_user', 'memory_per_user', 'gpu_per_user'):
        d[key] = json.loads(d[key])
    return d


def _clean_usage_users(cpu_per_user: dict, memory_per_user: dict,
                       gpu_per_user: dict, mapping: dict) -> dict:
    """Convert one snapshot's per-user values to display units."""
    users = set(cpu_per_user) | set(memory_per_user) | set(gpu_per_user)
    result = {}
    for raw_user in users:
        user = raw_user.strip()
        lower_user = user.lower()
        if (not user or lower_user in HISTORY_IGNORED_USERS
                or lower_user.startswith(('pid', 'eset'))):
            continue
        display_name = mapping.get(user, user)
        values = result.setdefault(display_name, [0.0, 0.0, 0.0])
        values[0] += cpu_per_user.get(raw_user, 0) / 1000
        values[1] += memory_per_user.get(raw_user, 0) / 1073741824
        values[2] += sum(gpu_per_user.get(raw_user, {}).values()) / 1073741824
    return result


def _iter_usage_rows(host: str, start_ts: int, end_ts: int):
    """Yield a host's per-user snapshots in chronological order."""
    start_year = datetime.fromtimestamp(start_ts).year
    end_year = datetime.fromtimestamp(end_ts).year
    for year, db_path in _host_db_paths(host):
        if not start_year <= year <= end_year:
            continue
        conn = _get_db(db_path)
        try:
            cursor = conn.execute('''
                SELECT timestamp, cpu_per_user, memory_per_user, gpu_per_user
                FROM snapshots
                WHERE host = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
            ''', (host, start_ts, end_ts))
            for row in cursor:
                yield row
        finally:
            conn.close()


def _load_mapping() -> dict:
    """Load the optional username mapping, defaulting to no aliases."""
    mapping_path = CONFIG_DIR / 'mapping.json'
    if not mapping_path.is_file():
        return {}
    with open(mapping_path, encoding='utf-8') as f:
        return json.load(f)


def _verify_totp(code: str) -> None:
    """Validate a one-time password against the shared container secret."""
    base32secret = os.getenv('TOTP_SECRET', '').strip()
    if not base32secret:
        logger.error('TOTP_SECRET is not configured')
        raise HTTPException(status_code=503, detail='TOTP authentication is not configured')
    try:
        valid = pyotp.TOTP(base32secret, interval=30, digits=6).verify(
            str(code).strip(), valid_window=2)
    except (TypeError, ValueError) as exc:
        logger.error('TOTP_SECRET is invalid: %s', exc)
        raise HTTPException(
            status_code=503,
            detail='TOTP authentication is not configured correctly',
        ) from exc
    if not valid:
        raise HTTPException(status_code=401, detail='Invalid TOTP code')


def _require_admin_ssh_key() -> str:
    """Return the explicitly mounted administrator key or disable the feature."""
    if (not os.path.isfile(ADMIN_SSH_KEY_PATH)
            or not os.access(ADMIN_SSH_KEY_PATH, os.R_OK)
            or os.path.getsize(ADMIN_SSH_KEY_PATH) == 0):
        raise HTTPException(
            status_code=503,
            detail='Port audit is disabled: administrator SSH key is not mounted',
        )
    return ADMIN_SSH_KEY_PATH


# 路由：获取所有服务器的最新数据
@app.get("/api/dashboard")
def get_dashboard():
    now = time.monotonic()
    cached = DASHBOARD_CACHE['data']
    if cached is not None and now - DASHBOARD_CACHE['timestamp'] < DASHBOARD_CACHE_TTL:
        return cached

    with DASHBOARD_CACHE_LOCK:
        now = time.monotonic()
        cached = DASHBOARD_CACHE['data']
        if cached is not None and now - DASHBOARD_CACHE['timestamp'] < DASHBOARD_CACHE_TTL:
            return cached

        hosts = list(HOSTS)
        with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as executor:
            rows = executor.map(_get_latest_snapshot, hosts)
            data = [_row_to_dict(row) for row in rows if row is not None]

        DASHBOARD_CACHE.update(timestamp=time.monotonic(), data=data)
        return data


# 路由：获取指定服务器的历史数据
@app.get("/api/history")
def get_history(host: str, start: float, end: float):
    if host not in HOSTS or start > end:
        return StreamingResponse(iter(()), media_type='application/x-ndjson')

    start_ts, end_ts = int(start), int(end)
    start_year = datetime.fromtimestamp(start_ts).year
    end_year = datetime.fromtimestamp(end_ts).year
    db_paths = [
        db_path for year, db_path in _host_db_paths(host)
        if start_year <= year <= end_year
    ]
    def stream_rows():
        for db_path in db_paths:
            # StreamingResponse may advance a sync generator on different
            # worker threads; batches themselves are still consumed serially.
            conn = _get_db(db_path, check_same_thread=False)
            try:
                cursor = conn.execute('''
                    SELECT timestamp,
                           cpu_usage_millicores, cpu_total_millicores,
                           memory_usage_bytes, memory_total_bytes,
                           gpu_usage_bytes, gpu_total_bytes
                    FROM snapshots
                    WHERE host = ? AND timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp
                ''', (host, start_ts, end_ts))
                while batch := cursor.fetchmany(1000):
                    lines = []
                    for row in batch:
                        record = dict(row)
                        for key in ('gpu_usage_bytes', 'gpu_total_bytes'):
                            record[key] = json.loads(record[key])
                        lines.append(json.dumps(record, ensure_ascii=False, separators=(',', ':')))
                    yield '\n'.join(lines) + '\n'
            finally:
                conn.close()

    return StreamingResponse(
        stream_rows(),
        media_type='application/x-ndjson',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


def _calculate_usage_stats(hosts: List[str], start: float, end: float,
                           progress_callback=None):
    """Aggregate per-user resource-hours and concurrent observed peaks."""
    selected_hosts = list(dict.fromkeys(hosts))
    invalid_hosts = [host for host in selected_hosts if host not in HOSTS]
    if not selected_hosts or invalid_hosts or start > end:
        raise HTTPException(status_code=400, detail='Invalid hosts or time range')

    start_ts, end_ts = int(start), int(end)
    mapping = _load_mapping()
    max_sample_gap = 300
    totals = {}
    peaks = {}
    current_global = {}
    host_values = {}
    host_timestamps = {}
    expiry_heap = []
    iterators = {}
    row_heap = []
    sample_count = 0
    last_progress_report = time.monotonic()

    def add_global(values_by_user: dict, direction: int):
        for user, values in values_by_user.items():
            current = current_global.setdefault(user, [0.0, 0.0, 0.0])
            for index in range(3):
                current[index] += direction * values[index]
                if abs(current[index]) < 1e-12:
                    current[index] = 0.0

    def update_peaks():
        for user, values in current_global.items():
            peak = peaks.setdefault(user, [0.0, 0.0, 0.0])
            for index in range(3):
                peak[index] = max(peak[index], values[index])

    def build_payload(progress: float, event_type: str):
        users = set(totals) | set(peaks)
        result = []
        for user in users:
            total = totals.get(user, [0.0, 0.0, 0.0])
            peak = peaks.get(user, [0.0, 0.0, 0.0])
            if max(total + peak) <= 0:
                continue
            result.append({
                'user': user,
                'cpu_core_hours': total[0],
                'cpu_peak_cores': peak[0],
                'memory_gib_hours': total[1],
                'memory_peak_gib': peak[1],
                'gpu_gib_hours': total[2],
                'gpu_peak_gib': peak[2],
            })
        result.sort(key=lambda item: (
            item['cpu_core_hours'] + item['memory_gib_hours']
            + item['gpu_gib_hours']), reverse=True)
        return {
            'type': event_type,
            'hosts': selected_hosts,
            'start': start_ts,
            'end': end_ts,
            'progress': min(100, max(0, progress)),
            'sample_count': sample_count,
            'users': result,
        }

    try:
        for host in selected_hosts:
            iterator = iter(_iter_usage_rows(host, start_ts, end_ts))
            iterators[host] = iterator
            first = next(iterator, None)
            if first is not None:
                heapq.heappush(row_heap, (first['timestamp'], host, first))

        while row_heap:
            timestamp = row_heap[0][0]

            while expiry_heap and expiry_heap[0][0] < timestamp:
                _, expired_host, observed_at = heapq.heappop(expiry_heap)
                if host_timestamps.get(expired_host) != observed_at:
                    continue
                add_global(host_values.get(expired_host, {}), -1)
                host_values[expired_host] = {}

            rows_at_timestamp = []
            while row_heap and row_heap[0][0] == timestamp:
                _, host, row = heapq.heappop(row_heap)
                rows_at_timestamp.append((host, row))

            for host, row in rows_at_timestamp:
                values = _clean_usage_users(
                    json.loads(row['cpu_per_user']),
                    json.loads(row['memory_per_user']),
                    json.loads(row['gpu_per_user']),
                    mapping,
                )
                previous_timestamp = host_timestamps.get(host)
                previous_values = host_values.get(host, {})
                if previous_timestamp is not None:
                    elapsed = timestamp - previous_timestamp
                    if 0 < elapsed <= max_sample_gap:
                        hours = elapsed / 3600
                        for user, resource_values in previous_values.items():
                            total = totals.setdefault(user, [0.0, 0.0, 0.0])
                            for index in range(3):
                                total[index] += resource_values[index] * hours

                add_global(previous_values, -1)
                add_global(values, 1)
                host_values[host] = values
                host_timestamps[host] = timestamp
                heapq.heappush(
                    expiry_heap, (timestamp + max_sample_gap, host, timestamp))
                sample_count += 1

                following = next(iterators[host], None)
                if following is not None:
                    heapq.heappush(
                        row_heap, (following['timestamp'], host, following))

            update_peaks()
            now = time.monotonic()
            if (progress_callback is not None
                    and now - last_progress_report >= 1):
                progress = ((timestamp - start_ts) / (end_ts - start_ts) * 100
                            if end_ts > start_ts else 100)
                progress_callback(build_payload(progress, 'progress'))
                last_progress_report = now
    finally:
        for iterator in iterators.values():
            close = getattr(iterator, 'close', None)
            if close is not None:
                close()

    return build_payload(100, 'complete')


@app.get('/api/usage_stats')
def get_usage_stats(hosts: List[str] = Query(...), start: float = 0,
                    end: float = 0):
    """Stream current usage aggregates as newline-delimited JSON."""
    selected_hosts = list(dict.fromkeys(hosts))
    invalid_hosts = [host for host in selected_hosts if host not in HOSTS]
    if not selected_hosts or invalid_hosts or start > end:
        raise HTTPException(status_code=400, detail='Invalid hosts or time range')

    def stream_results():
        messages = queue.Queue(maxsize=2)
        finished = object()

        def calculate():
            try:
                result = _calculate_usage_stats(
                    selected_hosts, start, end, messages.put)
                messages.put(result)
            except Exception as exc:
                logger.exception('Usage statistics aggregation failed')
                messages.put({
                    'type': 'error',
                    'detail': str(exc) or type(exc).__name__,
                })
            finally:
                messages.put(finished)

        worker = threading.Thread(target=calculate, daemon=True)
        worker.start()
        while True:
            message = messages.get()
            if message is finished:
                break
            yield json.dumps(
                message, ensure_ascii=False, separators=(',', ':')) + '\n'

    return StreamingResponse(
        stream_results(),
        media_type='application/x-ndjson',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )

# 路由：获取按用户汇总的资源使用情况
@app.get("/api/summary")
def get_summary(host: str):
    if host not in HOSTS:
        return []
    row = _get_latest_snapshot(host)

    if row is None:
        return []

    d = _row_to_dict(row)
    cpu_total = d['cpu_total_millicores']
    mem_total = d['memory_total_bytes']

    users = (set(d['cpu_per_user'].keys())
             | set(d['memory_per_user'].keys())
             | set(d['gpu_per_user'].keys()))

    mapping = _load_mapping()
    usage_by_name = {}
    for raw_user in users:
        user = raw_user.strip()
        lower_user = user.lower()
        if (not user or lower_user in HISTORY_IGNORED_USERS
                or lower_user.startswith(('pid', 'eset'))):
            continue

        display_name = mapping.get(user, user)
        usage = usage_by_name.setdefault(display_name, {
            'cpu': 0,
            'memory': 0,
            'gpu': {gpu_id: 0 for gpu_id in d['gpu_total_bytes']},
        })
        usage['cpu'] += d['cpu_per_user'].get(raw_user, 0)
        usage['memory'] += d['memory_per_user'].get(raw_user, 0)
        for gpu_id, value in d['gpu_per_user'].get(raw_user, {}).items():
            usage['gpu'][gpu_id] = usage['gpu'].get(gpu_id, 0) + value

    result = []
    for user, usage in usage_by_name.items():
        result.append(dict(
            host=host, timestamp=d['timestamp'], user=user,
            cpu_usage_millicores=usage['cpu'], cpu_total_millicores=cpu_total,
            memory_usage_bytes=usage['memory'], memory_total_bytes=mem_total,
            gpu_usage_bytes=usage['gpu'], gpu_total_bytes=d['gpu_total_bytes'],
            cpu_per_user={}, memory_per_user={}, gpu_per_user={},
        ))
    return result


class DiskUsageRecord(BaseModel):
    host: str             # 主机名
    time: float             # 时间戳
    disk: str             # 磁盘
    total: float            # 磁盘容量字节数
    free: float             # 剩余容量字节数
    usage: dict[str, float] # 用户使用字节数

# 路由：获取用户磁盘用量
@app.get("/api/disk", response_model=List[DiskUsageRecord])
def get_disk(host: str):
    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    mapping = _load_mapping()
    ssh = None
    sftp = None
    try:
        ssh = ssh_connect(copy.deepcopy(HOSTS[host]))
        sftp = ssh.open_sftp()
        yyyymm = datetime.now().strftime("%Y%m")
        with sftp.file(f'/var/monitor-disk-usage/{yyyymm}.jsonl', 'r') as f:
            raw_text = f.read().decode()
        df = pd.read_json(StringIO(raw_text), lines=True)
        df['disk'] = df['path'].str.rsplit('/', n=1).str[0]
        df['user'] = df['path'].str.rsplit('/', n=1).str[1]
        df['size'] = df['size'] / 1024 / 1024 / 1024
        df['user'] = df['user'].apply(lambda value: mapping.get(value, value))
        snapshot_time = df['time'].max()
        df = df.drop_duplicates(subset=['disk', 'user'], keep='last')

        result = []
        for disk, group in df.groupby('disk'):
            quoted_disk = shlex.quote(str(disk))
            output = safe_exec_command(
                ssh,
                f"df -B1 -- {quoted_disk} | "
                "awk 'NR==2{print $2/1024/1024/1024, $4/1024/1024/1024}'",
            )
            total, free = output.strip().split()
            result.append(DiskUsageRecord(
                host=host,
                time=snapshot_time,
                disk=disk,
                total=total,
                free=free,
                usage=group.set_index('user')['size'].to_dict(),
            ))
        return result
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning('Failed to read disk usage from %s: %s', host, exc)
        raise HTTPException(
            status_code=502,
            detail='Failed to read remote disk usage',
        ) from exc
    finally:
        if sftp is not None:
            sftp.close()
        if ssh is not None:
            ssh.close()



class PortRecord(BaseModel):
    host: str                       # 主机名
    timestamp: float                # 时间戳
    listen: str                # IP地址
    port: int                # 端口号
    user: str | None                # 用户名
    pid: int | None                 # 进程ID
    program: str | None             # 程序名

# 路由：获取开启的端口和开启端口的用户，需要验证用户的一次性密码 TOTP
@app.get("/api/ports", response_model=List[PortRecord])
def get_ports(
    host: str,
    totp_code: str = Header(..., alias='X-TOTP-Code'),
):
    _verify_totp(totp_code)

    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    admin_key_path = _require_admin_ssh_key()
    timestamp = time.time()
    mapping = _load_mapping()

    ssh = None
    try:
        server_config = copy.deepcopy(HOSTS[host])
        server_config.update({
            'username': 'root',
            'key_filename': admin_key_path,
        })
        ssh = ssh_connect(server_config)
    except Exception as e:
        logger.warning('Administrator SSH connection to %s failed: %s', host, e)
        raise HTTPException(
            status_code=502,
            detail='Failed to connect to host with the administrator key',
        ) from e
    try:
        data = safe_exec_command(
            ssh,
            "ps -eo user:100,pid | awk 'NR > 1'",
        )
        pid2user = {}
        for line in data.splitlines():
            user, pid = line.split()
            pid2user[pid] = user

        data = safe_exec_command(
            ssh,
            "netstat -tunlp | awk 'NR > 2 {print $4, $7}' | sort | uniq",
        )
        result = []
        for line in data.splitlines():
            fields = line.split(maxsplit=1)
            if not fields:
                continue
            addr = fields[0]
            detail = fields[1] if len(fields) > 1 else '-'
            listen, port = addr.rsplit(':', 1)
            if listen in ['127.0.0.1', '::']:
                listen = 'localhost'
            port = int(port)
            pid, program = detail.split('/', 1) if '/' in detail else (None, None)
            user = pid2user.get(pid, f'PID{pid}' if pid else None)
            pid = int(pid) if pid else None
            result.append(PortRecord(host=host, timestamp=timestamp,
                                     listen=listen, port=port,
                                     user=mapping.get(user, user),
                                     pid=pid, program=program))
        return result
    finally:
        ssh.close()


# 路由：返回服务器 IP
@app.get("/api/ip")
def get_ip(
    host: str,
    totp_code: str = Header(..., alias='X-TOTP-Code'),
):
    _verify_totp(totp_code)

    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    # hostname to IP
    ip = socket.gethostbyname(HOSTS[host]['hostname'])
    return ip


# 路由：返回用户名映射
@app.get("/api/mapping")
def get_mapping():
    return _load_mapping()


# 路由：返回支持的主机列表 (List[str])
@app.get("/api/hosts", response_model=List[str])
async def get_hosts():
    return list(HOSTS.keys())


@app.get("/api/filesystems")
def get_filesystems(host: str, refresh: bool = False):
    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")

    cache_key = host
    requested_at = time.monotonic()
    cached = FILESYSTEM_CACHE.get(cache_key)
    if cached and not refresh and requested_at - cached['created_at'] < FILESYSTEM_CACHE_TTL:
        return cached['payload']

    with FILESYSTEM_LOCKS[host]:
        cached = FILESYSTEM_CACHE.get(cache_key)
        if cached:
            is_fresh = time.monotonic() - cached['created_at'] < FILESYSTEM_CACHE_TTL
            refreshed_for_request = cached['created_at'] >= requested_at
            if (not refresh and is_fresh) or refreshed_for_request:
                return cached['payload']

        ssh = None
        try:
            ssh = ssh_connect(copy.deepcopy(HOSTS[host]))
            output = safe_exec_command(
                ssh,
                "LC_ALL=C timeout 8s df -B1 -PT 2>/dev/null",
                timeout=12,
            )
            filesystems = []
            for line in output.splitlines()[1:]:
                fields = line.split(maxsplit=6)
                if len(fields) != 7:
                    continue
                device, fs_type, total, used, available, _, mountpoint = fields
                mountpoint = mountpoint.replace('\\040', ' ')
                if (fs_type.lower() in VIRTUAL_FILESYSTEM_TYPES
                        or mountpoint in HIDDEN_FILESYSTEM_MOUNTPOINTS):
                    continue
                try:
                    total_bytes = int(total)
                    used_bytes = int(used)
                    available_bytes = int(available)
                except ValueError:
                    continue
                if total_bytes <= 0:
                    continue
                usable_bytes = used_bytes + available_bytes
                usage_percent = (used_bytes / usable_bytes * 100
                                 if usable_bytes > 0 else 100)
                filesystems.append({
                    'device': device.replace('\\040', ' '),
                    'filesystem_type': fs_type,
                    'mountpoint': mountpoint,
                    'total_bytes': total_bytes,
                    'used_bytes': used_bytes,
                    'available_bytes': available_bytes,
                    'usage_percent': usage_percent,
                })

            if not filesystems:
                raise RuntimeError("df did not return any usable filesystems")
            payload = {
                'host': host,
                'timestamp': int(time.time()),
                'filesystems': filesystems,
            }
            FILESYSTEM_CACHE[cache_key] = {
                'created_at': time.monotonic(),
                'payload': payload,
            }
            return payload
        except TimeoutError as e:
            raise HTTPException(status_code=504, detail=str(e)) from e
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Failed to read filesystems from %s: %s", host, e)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to read filesystems: {e}",
            ) from e
        finally:
            if ssh is not None:
                ssh.close()


# 路由：通过 SSH 获取指定服务器的硬件与系统详情
@app.get("/api/server_info", response_class=PlainTextResponse)
def get_server_info(host: str):
    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    try:
        ssh = ssh_connect(HOSTS[host])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to host: {str(e)}")

    try:
        info = {}
        # Hostname
        info["💻 Hostname"] = safe_exec_command(ssh, "hostname -f 2>/dev/null || hostname").strip()
        # CPU Model
        info["🧠 CPU Model"] = safe_exec_command(ssh, "lscpu | grep 'Model name' | awk -F: '{print $2}'").strip()
        # Cores / Threads
        physical = safe_exec_command(ssh, "grep 'core id' /proc/cpuinfo | sort -u | wc -l").strip()
        logical = safe_exec_command(ssh, "nproc").strip()
        info["⚙️ Cores / Threads"] = f"{physical} C / {logical} T"
        # CPU Frequency
        output = safe_exec_command(ssh, "lscpu | grep 'MHz'").strip()
        frequency = {}
        for line in output.splitlines():
            k, v = line.split(':')
            frequency[k.strip()] = v.strip()
        freq = frequency.get('CPU MHz', 'N/A')
        if freq == 'N/A':
            output2 = safe_exec_command(ssh, "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").strip()
            freq = int(output2) / 1024 # kHz -> MHz
        else:
            freq = float(freq)
        freq_min = float(frequency.get('CPU min MHz', 'N/A'))
        freq_max = float(frequency.get('CPU max MHz', 'N/A'))
        info["⏱️ CPU Frequency"] = f"{freq:.2f} MHz (min={freq_min:.0f} MHz, max={freq_max:.0f} MHz)"
        # SIMD Support
        output = safe_exec_command(ssh, "grep '^flags' /proc/cpuinfo | head -n 1").strip()
        flags = set(output.split(':', 2)[1].split())
        info["🧩 SIMD Support"] = f"AVX={'avx' in flags}, AVX2={'avx2' in flags}, AVX512={any('avx512f' in f for f in flags)}"
        # L3 Cache
        info["🗃️ L3 Cache"] = safe_exec_command(ssh, "lscpu | grep 'L3 cache' | awk -F: '{print $2}'").strip()
        # NUMA Nodes
        info["🔀 NUMA Nodes"] = safe_exec_command(ssh, "lscpu | grep 'NUMA node(s)' | awk -F: '{print $2}'").strip()
        # Total Memory
        output = safe_exec_command(ssh, 'cat /proc/meminfo').strip()
        lines = [line for line in output.splitlines() if 'MemTotal' in line]
        assert len(lines) == 1, output
        mem_kB = int(lines[0].removeprefix('MemTotal:').strip().removesuffix('kB').strip())
        info["💾 Memory Total"] = f"{mem_kB / 1024 / 1024:.0f} GB"
        # GPU Model
        output = safe_exec_command(ssh, "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader").strip()
        try:
            df = pd.read_csv(StringIO(output), sep=',', names=['Name', 'Memory'])
            df['Name'] = df['Name'].str.strip()
            df['Memory'] = df['Memory'].str.strip()
            gpu_model = ""
            for name in df['Name'].unique():
                if gpu_model != "":
                    gpu_model += ", "
                count = (df['Name'] == name).sum()
                mem_MB = df.loc[df['Name'] == name, 'Memory'].iloc[0]
                mem_GB = int(mem_MB.removesuffix('MiB').strip()) / 1024
                gpu_model += f"{count}*{name} ({mem_GB:.0f} GiB) "
            if gpu_model == "":
                gpu_model = "N/A"
        except Exception:
            gpu_model = f"N/A ({output})"
        info["🎮 GPU Model"] = gpu_model
        # CUDA Version
        info["🚀 CUDA Version"] = safe_exec_command(ssh, "nvidia-smi | grep -i 'CUDA Version' | head -n1 | awk -F 'CUDA Version: ' '{print $2}' | awk '{print $1}'").strip() or "N/A"
        # OS Version
        output = safe_exec_command(ssh, 'cat /etc/os-release').strip()
        lines = [line for line in output.splitlines() if 'PRETTY_NAME' in line]
        assert len(lines) == 1, output
        info["🐧 OS Version"] = lines[0].strip().removeprefix('PRETTY_NAME=').strip('"')
        # Kernel Version
        info["🧱 Kernel Version"] = safe_exec_command(ssh, "uname -a").strip()
        # Conclude
        max_len = max(len(k) for k in info)
        content = '\n'.join([f"{k:{max_len}} : {v}" for k, v in info.items()])
        max_len = max(map(len, content.splitlines()))
        content = (
            '=' * max_len + '\n' +
            '🔍 Server Hardware Info Summary\n' +
            '=' * max_len + '\n' +
            content + '\n' +
            '=' * max_len
        )
        return PlainTextResponse(content=content)
    except Exception as e:
        return PlainTextResponse(content=(
            f"Error retrieving server info: [{type(e)}] {e}\n"
            f"{traceback.format_exc()}"
        ), status_code=500)
    finally:
        ssh.close()


# 路由：返回前端HTML页面
@app.get("/", response_class=HTMLResponse)
def index():
    with open(TEMPLATE_DIR / 'index.html', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


# 详情页 HTML
@app.get("/server", response_class=HTMLResponse)
def server_page():
    with open(TEMPLATE_DIR / 'server.html', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


# 路由：获取图标 ./assets/favicon.ico
@app.get("/favicon.ico")
async def get_favicon():
    return FileResponse(BASE_DIR / 'assets' / 'favicon.ico')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
