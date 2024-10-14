import os
import yaml
import time
import json
import subprocess
import pandas as pd
from typing import List, Union
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# 获取数据文件路径
DATA_DIR = './data'
HOSTS = list(yaml.load(open('hosts.yml'), Loader=yaml.FullLoader).keys())

# 初始化 FastAPI 实例
app = FastAPI()

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
                              user=None, cpu_free=data['cpu-free'], memory_free=data['memory-free']))
    return records

# 路由：获取指定服务器的历史数据
@app.get("/api/history", response_model=List[Record])
async def get_history(host: str, start: float, end: float):
    file_path = os.path.join(DATA_DIR, f'{host}.json')
    if host not in HOSTS or not os.path.exists(file_path): return []
    records = []
    with open(file_path, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                if 'timestamp' not in data:
                    data['timestamp'] = time.mktime(time.strptime(data['time'], "%Y-%m-%d %H:%M:%S"))
                if 'cpu-free' not in data: data['cpu-free'] = None
                if 'memory-free' not in data: data['memory-free'] = None
                if start <= data['timestamp'] <= end:
                    records.append(Record(host=host, timestamp=data['timestamp'], 
                                          cpu=data['cpu'], memory=data['memory'],
                                          cuda=data['cuda'], cuda_free=data['cuda-free'],
                                          user=None, cpu_free=data['cpu-free'], memory_free=data['memory-free']))
            except Exception as e:
                print(e)
    return records


# 路由：获取按用户汇总的资源使用情况
@app.get("/api/summary", response_model=List[Record])
async def get_summary(host: str):
    records = []
    mapping = json.load(open('mapping.json')) if os.path.exists('mapping.json') else {}
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


# 路由：返回前端HTML页面
@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html") as f:
        return HTMLResponse(content=f.read())


@app.get("/css/{filename}")
async def get_css(filename: str):
    return FileResponse(f"templates/css/{filename}")


@app.get("/js/{filename}")
async def get_js(filename: str):
    return FileResponse(f"templates/js/{filename}")


# 路由：获取图标 ./assets/favicon.ico
@app.get("/favicon.ico")
async def get_favicon():
    return FileResponse("assets/favicon.ico")

# 路由：返回支持的主机列表 (List[str])
@app.get("/api/hosts", response_model=List[str])
async def get_hosts():
    return HOSTS

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
