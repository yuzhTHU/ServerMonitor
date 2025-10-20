import os
import yaml
import time
import json
import subprocess
import pandas as pd
from typing import List, Union, Tuple, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel

# 获取数据文件路径
DATA_DIR = './data'
HOSTS = yaml.load(open('hosts.yml'), Loader=yaml.FullLoader)

# 初始化 FastAPI 实例
app = FastAPI(docs_url=None, redoc_url=None)

# 数据模型
class Record(BaseModel):
    timestamp: float                # 时间戳
    host: str                       # 主机名
    user: Union[str, None]          # 用户名
    cpu: float                      # CPU 使用率, 单位: %
    memory: float                   # 内存使用率, 单位: %
    cuda: List[float]               # CUDA 显存使用率, 单位: %
    cpu_free: Union[float, None]    # CPU 剩余核数
    memory_free: Union[float,None]  # 内存剩余量, 单位: MiB
    cuda_free: Union[List[float], None] # CUDA 显存剩余量, 单位: MiB


def safe_exec_command(client, command, timeout=60):
    stdin, stdout, stderr = client.exec_command(command)
    
    def read_output(out, result_holder):
        result_holder.append(out.read().decode())

    result = []
    thread = threading.Thread(target=read_output, args=(stdout, result))
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        stdout.channel.close()  # 强制关闭channel
        thread.join()
        raise TimeoutError(f"Command timed out: {command}")
    return result[0]


def read_last_line(file_path, n=1):
    if not os.path.exists(file_path): return None
    return subprocess.check_output(['tail', '-n', str(n), file_path]).decode('utf-8')


# 路由：获取所有服务器的最新数据
@app.get("/api/dashboard", response_model=List[Record])
async def get_dashboard():
    records = []
    for host in HOSTS:
        file_path = os.path.join(DATA_DIR, f'{host}.json')
        if not os.path.exists(file_path): continue
        data = json.loads(read_last_line(file_path))
        if 'timestamp' not in data:
            data['timestamp'] = time.mktime(time.strptime(data['time'], "%Y-%m-%d %H:%M:%S"))
        if 'cpu-free' not in data: data['cpu-free'] = None
        if 'memory-free' not in data: data['memory-free'] = None
        records.append(Record(host=data['host'], timestamp=data['timestamp'],
                              cpu=data['cpu'], memory=data['memory'],
                              cuda=data['cuda'], cuda_free=data['cuda-free'],
                              user=None, cpu_free=data['cpu_free'], memory_free=data['memory_free']))
    return records


def __get_timestamp_from_line(line: str) -> float:
    """
    从一行 JSON 字符串里提取 timestamp。如果没有 'timestamp' 字段，
    就用 time.strptime + time.mktime 解析 'time' 字段。
    """
    data = json.loads(line)
    if 'timestamp' not in data:
        # 假设 time 格式都是 "%Y-%m-%d %H:%M:%S"
        data['timestamp'] = time.mktime(time.strptime(data['time'], "%Y-%m-%d %H:%M:%S"))
    return float(data['timestamp'])

def __find_start_offset(file_path: str, start_ts: float) -> int:
    """
    在 sorted-by-timestamp 的文件里，使用二分查找来定位第一个 timestamp >= start_ts 的“附近”字节偏移。
    返回值是一个 file.seek() 可以使用的字节偏移位置，我们会在此偏移再做一次 readline() 丢掉残行。
    """
    file_size = os.path.getsize(file_path)
    low, high = 0, file_size
    result_offset = 0

    with open(file_path, 'r', encoding='utf-8') as f:
        while low <= high:
            mid = (low + high) // 2
            f.seek(mid)

            # 丢弃当前这一行的不完整部分
            f.readline()
            line = f.readline()
            if not line:
                # 如果 mid 已经靠近文件末尾，往前移动高位
                high = mid - 1
                continue

            try:
                ts = __get_timestamp_from_line(line)
            except Exception:
                # 如果 JSON 解析失败，就往后或往前稍微移动一点再试
                # 这里简单起见，把 mid 往后调一点
                low = mid + 1
                continue

            if ts < start_ts:
                # 目标在文件后半段
                low = mid + 1
            else:
                # ts >= start_ts，记住这个位置有可能是我们要的“起点”
                result_offset = mid
                high = mid - 1

    return result_offset

# 路由：获取指定服务器的历史数据
@app.get("/api/history", response_model=List[Record])
async def get_history(host: str, start: float, end: float):
    file_path = os.path.join(DATA_DIR, f'{host}.json')
    if host not in HOSTS or not os.path.exists(file_path): return []
    records = []
    # 1. 先用二分查找定位到“起点偏移”
    start_offset = __find_start_offset(file_path, start)

    with open(file_path, 'r', encoding='utf-8') as f:
        # 2. 把文件指针移动到 start_offset 处，再丢掉这一行的不完整部分
        f.seek(start_offset)
        f.readline()

        # 3. 从此处开始顺序读取，碰到 timestamp > end 就直接中止
        for line in f:
            try:
                data = json.loads(line)

                # 如果没有 'timestamp'，补充计算一下
                if 'timestamp' not in data:
                    data['timestamp'] = time.mktime(time.strptime(data['time'], "%Y-%m-%d %H:%M:%S"))
                # 补齐可能缺失的字段
                if 'cpu-free' not in data:      data['cpu-free'] = None
                if 'memory-free' not in data:   data['memory-free'] = None

                ts = float(data['timestamp'])

                # 如果读到的记录还没到 start，直接跳过
                if ts < start:
                    continue

                # 如果超过 end，就可以停止整个循环
                if ts > end:
                    break

                # ts 在 [start, end] 区间内，就 append 到结果
                records.append(
                    Record(
                        host=host,
                        timestamp=ts,
                        cpu=data['cpu'],
                        memory=data['memory'],
                        cuda=data['cuda'],
                        cuda_free=data.get('cuda-free'),
                        user=None,
                        cpu_free=data.get('cpu-free'),
                        memory_free=data.get('memory-free'),
                    )
                )
            except Exception as e:
                # 如果某行解析失败，打印一下日志并跳过
                print(f"parse error: {e}  --  line: {line.strip()}")
                continue

    return records

# 路由：获取按用户汇总的资源使用情况
@app.get("/api/summary", response_model=List[Record])
async def get_summary(host: str):
    records = []
    mapping = json.load(open('mapping.json', encoding='utf-8')) if os.path.exists('mapping.json') else {}
    file_path = os.path.join(DATA_DIR, f'{host}.json')
    if host not in HOSTS or not os.path.exists(file_path):
        return []
    data = json.loads(read_last_line(file_path))
    user2cpu = {}
    for user, value in data['cpu_per_user']: user2cpu[user] = user2cpu.get(user, 0.0) + value
    user2mem = {}
    for user, value in data['memory_per_user']: user2mem[user] = user2mem.get(user, 0.0) + value
    user2cuda = {}
    for cuda, user, value in data['cuda_per_user']:
        if user not in user2cuda: user2cuda[user] = [0.0] * len(data['cuda'])
        user2cuda[user][int(cuda.removeprefix('cuda:'))] += value
    users = set(user2cpu.keys()) | set(user2mem.keys()) | set(user2cuda.keys())
    for user in users:
        if user.startswith('PID'): continue # ignore unknown username
        if user in [ # ignore system users
            'www-data', 'root', 'nobody', 'messagebus', 'syslog', 
            'systemd-timesync', 'earlyoom', 'uuidd', 'colord', 'postfix', '_rpc', 
            'postgres', 'systemd-resolve', 'nvidia-persistenced', 
            'systemd-network', 'whoopsie', 'kernoops', 'systemd-oom',
            'Debian-snmp', 'daemon', 'mas', 'libvirt-dnsmasq', 'rtkit', 'lp', 'avahi', 'zabbix', 'gdm'
        ]: continue
        records.append(Record(host=host, timestamp=data['timestamp'],
                                cpu=user2cpu.get(user, 0.0), memory=user2mem.get(user, 0.0),
                                cuda=user2cuda.get(user, [0.0] * len(data['cuda'])), 
                                cuda_free=None, user=mapping.get(user, user),
                                cpu_free=None, memory_free=None))
    return records


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

    from io import StringIO
    import paramiko
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
    with sftp.file('/var/monitor-disk-usage/202510.jsonl', 'r') as f:
        raw_text = f.read().decode()
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
    import pyotp
    with open('./keys/TOTP', 'r') as f:
        base32secret = f.read().strip()
    totp = pyotp.TOTP(base32secret, interval=30, digits=6)
    if not totp.verify(secret, valid_window=2):
        raise HTTPException(status_code=401, detail="Invalid TOTP secret")

    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    timestamp = time.time()
    mapping = json.load(open('mapping.json', encoding='utf-8')) if os.path.exists('mapping.json') else {}

    import paramiko
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
    import pyotp
    with open('./keys/TOTP', 'r') as f:
        base32secret = f.read().strip()
    totp = pyotp.TOTP(base32secret, interval=30, digits=6)
    if not totp.verify(secret, valid_window=2):
        raise HTTPException(status_code=401, detail="Invalid TOTP secret")

    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")
    # hostname to IP
    import socket
    ip = socket.gethostbyname(HOSTS[host]['hostname'])
    return ip


# 路由：返回支持的主机列表 (List[str])
@app.get("/api/hosts", response_model=List[str])
async def get_hosts():
    return list(HOSTS.keys())


# 路由：获取指定服务器的硬件/系统详情（通过 SSH 上传并执行 get_server_info.py）
@app.get("/api/server_info", response_class=PlainTextResponse)
async def get_server_info(host: str):
    if host not in HOSTS:
        raise HTTPException(status_code=404, detail="Host not found")

    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    server_config = HOSTS[host].copy()
    if 'sock' in server_config:
        server_config['sock'] = paramiko.ProxyCommand(server_config['sock'])
    try:
        ssh.connect(**server_config, timeout=15)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to host: {str(e)}")

    sftp = None
    remote_path = "/tmp/get_server_info.py"
    try:
        def _exec(cmd: str):
            stdin, stdout, stderr = ssh.exec_command(cmd)
            out = stdout.read().decode(errors='ignore')
            err = stderr.read().decode(errors='ignore')
            # 获取退出码
            exit_status = stdout.channel.recv_exit_status()
            return exit_status, out, err

        sftp = ssh.open_sftp()
        # 将本地脚本上传到远端临时路径
        sftp.put("get_server_info.py", remote_path)

        # 第一次尝试执行脚本
        code, out, err = _exec(f"python3 {remote_path}")

        # 如果因为缺少 psutil 失败，尝试安装后重试
        # if code != 0 and ('ModuleNotFoundError' in err or 'No module named' in err) and 'psutil' in err:
        #     # 优先使用 python3 -m pip，其次 pip3
        #     _exec("python3 -m pip --version >/dev/null 2>&1 || true")
        #     _exec("python3 -m pip install --user -q psutil || pip3 install --user -q psutil || true")
        #     # 刷新 PATH 以便找到 --user 安装包（某些环境下需要）
        #     _exec("export PYTHONUSERBASE=~/.local; export PATH=~/.local/bin:$PATH; true")
        #     code, out, err = _exec(f"python3 {remote_path}")

        # 清理远端脚本
        try:
            sftp.remove(remote_path)
        except Exception:
            pass

        # 如果仍失败，则使用基础命令回退，避免前端报错
        # if code != 0 and not out:
        #     sections = []
        #     def add(title: str, cmd: str):
        #         c, o, e = _exec(cmd)
        #         text = o.strip() if o.strip() else e.strip()
        #         sections.append(f"{title}\n{text}\n")

        #     add("Hostname", "hostname")
        #     add("CPU Model", "lscpu | grep -E 'Model name|Architecture|CPU\(s\)|Thread|Core|Socket|NUMA' || true")
        #     add("Memory", "free -h || cat /proc/meminfo | head -n 5")
        #     add("OS / Kernel", "uname -a")
        #     add("Python", "python3 --version || python --version || true")
        #     # GPU 信息（若有）
        #     add("NVIDIA GPUs", "nvidia-smi --query-gpu=name,memory.total,memory.free,utilization.gpu --format=csv,noheader 2>/dev/null || echo 'nvidia-smi not found'")

        #     fallback_text = (
        #         "="*60 + "\n" +
        #         "Server Info (fallback mode)\n" +
        #         "="*60 + "\n\n" +
        #         "\n\n".join(sections)
        #     )
        #     # 把原始错误也带上结尾，方便排查
        #     if err.strip():
        #         fallback_text += f"\n\nError Detail:\n{err.strip()}\n"
        #     return PlainTextResponse(content=fallback_text)

        # 正常返回脚本输出（或包含少量 stderr 的输出）
        return PlainTextResponse(content=out if out else err)
    finally:
        if sftp:
            sftp.close()
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
