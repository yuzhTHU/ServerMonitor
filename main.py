import os
import yaml
import time
import json
import pyotp
import socket
import dotenv
import sqlite3
import paramiko
import traceback
import subprocess
import pandas as pd
from io import StringIO
from logging import getLogger
from datetime import datetime
from src.logger import set_logger
from typing import List, Union, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel
from src.ssh_connect import ssh_connect, safe_exec_command

dotenv.load_dotenv()
set_logger('ServerMonitor', file='./log/web.log', basename='my')
logger = getLogger(f'my.web')

# 获取数据文件路径
DATA_DIR = './data'
HOSTS = yaml.load(open('hosts.yml'), Loader=yaml.FullLoader)

# 初始化 FastAPI 实例
app = FastAPI(docs_url=None, redoc_url=None)


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


def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
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


# 路由：获取所有服务器的最新数据
@app.get("/api/dashboard")
async def get_dashboard():
    rows = []
    for host in HOSTS:
        row = _get_latest_snapshot(host)
        if row is not None:
            rows.append(row)
    return [_row_to_dict(r) for r in rows]


# 路由：获取指定服务器的历史数据
@app.get("/api/history")
async def get_history(host: str, start: float, end: float):
    if host not in HOSTS or start > end:
        return []

    start_ts, end_ts = int(start), int(end)
    start_year = datetime.fromtimestamp(start_ts).year
    end_year = datetime.fromtimestamp(end_ts).year
    rows = []
    for year, db_path in _host_db_paths(host):
        if year < start_year or year > end_year:
            continue
        conn = _get_db(db_path)
        try:
            rows.extend(conn.execute('''
                SELECT * FROM snapshots
                WHERE host = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
            ''', (host, start_ts, end_ts)).fetchall())
        finally:
            conn.close()
    return [_row_to_dict(r) for r in rows]

# 路由：获取按用户汇总的资源使用情况
@app.get("/api/summary")
async def get_summary(host: str):
    if host not in HOSTS:
        return []
    row = _get_latest_snapshot(host)

    if row is None:
        return []

    d = _row_to_dict(row)
    cpu_total = d['cpu_total_millicores']
    mem_total = d['memory_total_bytes']

    ignored_users = {
        'www-data', 'root', 'nobody', 'messagebus', 'syslog',
        'systemd-timesync', 'earlyoom', 'uuidd', 'colord', 'postfix', '_rpc',
        'postgres', 'systemd-resolve', 'nvidia-persistenced',
        'systemd-network', 'whoopsie', 'kernoops', 'systemd-oom',
        'Debian-snmp', 'daemon', 'mas', 'libvirt-dnsmasq', 'rtkit', 'lp', 'avahi', 'zabbix', 'gdm',
    }

    users = (set(d['cpu_per_user'].keys())
             | set(d['memory_per_user'].keys())
             | set(d['gpu_per_user'].keys()))

    result = []
    for user in users:
        if user.startswith('PID') or user in ignored_users:
            continue
        user_cpu = d['cpu_per_user'].get(user, 0)
        user_mem = d['memory_per_user'].get(user, 0)
        user_gpus = d['gpu_per_user'].get(user, {})
        user_gpu_bytes = {gid: user_gpus.get(gid, 0) for gid in d['gpu_total_bytes']}

        result.append(dict(
            host=host, timestamp=d['timestamp'], user=user,
            cpu_usage_millicores=user_cpu, cpu_total_millicores=cpu_total,
            memory_usage_bytes=user_mem, memory_total_bytes=mem_total,
            gpu_usage_bytes=user_gpu_bytes, gpu_total_bytes=d['gpu_total_bytes'],
            cpu_per_user={}, memory_per_user={}, gpu_per_user={},
        ))
    return result


class DiskUsageRecord(BaseModel):
    host: str             # 主机名
    time: float             # 时间戳
    disk: str             # 磁盘
    total: float            # 磁盘容量字节数
    free: float             # 剩余容量字节数
    usage: Dict[str, float] # 用户使用字节数

# 路由：获取用户磁盘用量
@app.get("/api/disk", response_model=List[DiskUsageRecord])
async def get_disk(host: str):
    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    mapping = json.load(open('mapping.json', encoding='utf-8')) if os.path.exists('mapping.json') else {}

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(**HOSTS[host], timeout=10)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to host: {str(e)}")

    # _, stdout, _ = ssh.exec_command("df -B1 | grep '^/dev' | grep ' /data' | awk '{total[$6] += $2/1024/1024/1024; free[$6] += $4/1024/1024/1024} END {for (u in total) print u, total[u], free[u]}'")
    # output = stdout.read().decode()
    # df = pd.DataFrame([line.split() for line in output.splitlines()], columns=['disk', 'total', 'free'])
    # df['total'] = df['total'].astype(float)
    # df['free'] = df['free'].astype(float)
    # df = df.set_index('disk').sort_index()

    sftp = ssh.open_sftp()
    yyyymm = datetime.now().strftime("%Y%m")
    try:
        with sftp.file(f'/var/monitor-disk-usage/{yyyymm}.jsonl', 'r') as f:
            raw_text = f.read().decode()
    except FileNotFoundError:
        return []
    df = pd.read_json(StringIO(raw_text), lines=True)
    df['disk'] = df['path'].str.rsplit('/', n=1).str[0]
    df['user'] = df['path'].str.rsplit('/', n=1).str[1]
    df['size'] = df['size']/1024/1024/1024
    df['user'] = df['user'].apply(lambda x: mapping.get(x, x))

    time = df['time'].max()
    # df = df[df['time'] == time].reset_index()
    df = df.drop_duplicates(subset=['disk', 'user'], keep='last')

    result = []
    for disk, group in df.groupby('disk'):
        _, stdout, _ = ssh.exec_command(f"df -B1 \"{disk}\" | awk 'NR==2{{print $2/1024/1024/1024, $4/1024/1024/1024}}'")
        output = stdout.read().decode()
        total, free = output.strip().split()
        
        result.append(DiskUsageRecord(host=host, time=time,
                                      disk=disk, total=total, free=free,
                                      usage=group.set_index('user')['size'].to_dict()
                                      ))
    return result



class PortRecord(BaseModel):
    host: str                       # 主机名
    timestamp: float                # 时间戳
    listen: str                # IP地址
    port: int                # 端口号
    user: Union[str, None]                # 用户名   
    pid: Union[int, None]                # 进程ID
    program: Union[str, None]               # 程序名

# 路由：获取开启的端口和开启端口的用户，需要验证用户的一次性密码 TOTP
@app.get("/api/ports", response_model=List[PortRecord])
async def get_ports(host: str, secret: str):
    base32secret = os.getenv('TOTP_SECRET')
    totp = pyotp.TOTP(base32secret, interval=30, digits=6)
    if not totp.verify(secret, valid_window=2):
        raise HTTPException(status_code=401, detail="Invalid TOTP secret")

    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    timestamp = time.time()
    mapping = json.load(open('mapping.json', encoding='utf-8')) if os.path.exists('mapping.json') else {}

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(**{**HOSTS[host], 'username': 'root', 'key_filename': '/home/yumeow/.ssh/LABNAS/id_rsa'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to host: {str(e)}")

    _, stdout, _ = ssh.exec_command("ps -eo user:100,pid | awk 'NR > 1'")
    pid2user = {}
    for line in stdout.read().decode().splitlines():
        user, pid = line.split()
        pid2user[pid] = user

    _, stdout, _ = ssh.exec_command("netstat -tunlp | awk 'NR > 2 {print $4, $7}' | sort | uniq")
    data = stdout.read().decode()

    result = []
    for line in data.splitlines():
        addr, detail = line.split(' ')
        listen, port = addr.rsplit(':', 1)
        if listen in ['127.0.0.1', '::']: listen = 'localhost'
        port = int(port)
        pid, program = detail.split('/', 1) if '/' in detail else (None, None)
        user = pid2user.get(pid, f'PID{pid}' if pid else None)
        pid = int(pid) if pid else None
        result.append(PortRecord(host=host, timestamp=timestamp,
                                 listen=listen, port=port,
                                 user=mapping.get(user, user),
                                 pid=pid, program=program))
    return result


# 路由：返回服务器 IP
@app.get("/api/ip")
async def get_ip(host: str, secret: str):
    with open('./keys/TOTP', 'r') as f:
        base32secret = f.read().strip()
    totp = pyotp.TOTP(base32secret, interval=30, digits=6)
    if not totp.verify(secret, valid_window=2):
        raise HTTPException(status_code=401, detail="Invalid TOTP secret")

    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    # hostname to IP
    ip = socket.gethostbyname(HOSTS[host]['hostname'])
    return ip


# 路由：返回用户名映射
@app.get("/api/mapping")
async def get_mapping():
    if os.path.exists('mapping.json'):
        with open('mapping.json', encoding='utf-8') as f:
            return json.load(f)
    return {}


# 路由：返回支持的主机列表 (List[str])
@app.get("/api/hosts", response_model=List[str])
async def get_hosts():
    return list(HOSTS.keys())


# 路由：获取指定服务器的硬件/系统详情（通过 SSH 上传并执行 get_server_info.py）
@app.get("/api/server_info", response_class=PlainTextResponse)
async def get_server_info(host: str):
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
async def index():
    with open("templates/index.html", encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


@app.get("/css/{filename}")
async def get_css(filename: str):
    return FileResponse(f"templates/css/{filename}")


@app.get("/js/{filename}")
async def get_js(filename: str):
    return FileResponse(f"templates/js/{filename}")

@app.get("/html/{filename}")
async def get_js(filename: str):
    return FileResponse(f"templates/html/{filename}")


# 详情页 HTML
@app.get("/server", response_class=HTMLResponse)
async def server_page():
    with open("templates/server.html", encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


# 路由：获取图标 ./assets/favicon.ico
@app.get("/favicon.ico")
async def get_favicon():
    return FileResponse("assets/favicon.ico")


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
