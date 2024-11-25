import os
import time
import json
import paramiko
import threading
from logging import getLogger
from logger import set_logger
import yaml

def get_stats(client, save=False):
    record = dict(timestamp=time.time())

    # 获取CPU使用率和总核数
    _, stdout, _ = client.exec_command("top -b -n 3 -d 1 | grep 'Cpu(s)' | tail -n1")
    record['cpu'] = float(stdout.read().decode().split()[1])
    _, stdout, _ = client.exec_command("nproc")
    record['cpu-free'] = int(stdout.read().decode().strip()) * (1 - record['cpu'] / 100)

    # 获取内存使用率和总内存
    _, stdout, _ = client.exec_command("free -m | awk 'NR==2{print $3/$2*100, $7}'")
    record['memory'], record['memory-free'] = stdout.read().decode().strip().split()
    record['memory'], record['memory-free'] = float(record['memory']), float(record['memory-free'])

    # 获取每个GPU的显存使用情况和总显存
    _, stdout, _ = client.exec_command("nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits")
    indexes, memory_useds, memory_totals = [], [], []
    for gpu in stdout.read().decode().strip().split('\n'):
        index, memory_used, memory_total = gpu.split(',')
        indexes.append(int(index))
        memory_useds.append(float(memory_used))
        memory_totals.append(float(memory_total))
    record['cuda'] = [None] * (max(indexes) + 1)
    record['cuda-free'] = [None] * (max(indexes) + 1)
    for index, memory_used, memory_total in zip(indexes, memory_useds, memory_totals):
        record['cuda'][index] = memory_used / memory_total * 100
        record['cuda-free'][index] = memory_total - memory_used
    
    # 获取系统上各个用户的 CPU 使用情况
    _, stdout, _ = client.exec_command("ps -eo user:100,%cpu | awk 'NR > 1 {cpu[$1] += $2} END {for (u in cpu) print u, cpu[u]}' | sort -k2 -nr")
    record['cpu_per_user'] = []
    for line in stdout.read().decode().splitlines()[1:]: # Skip the header
        user, cpu_usage = line.split()
        record['cpu_per_user'].append((user, float(cpu_usage)))

    # 获取系统上各个用户的内存使用情况
    _, stdout, _ = client.exec_command("ps -eo user:100,%mem | awk 'NR > 1 {mem[$1] += $2} END {for (u in mem) print u, mem[u]}' | sort -k2 -nr")
    record['memory_per_user'] = []
    for line in stdout.read().decode().splitlines()[1:]:  # Skip the header
        user, memory_usage = line.split()
        record['memory_per_user'].append((user, float(memory_usage)))

    # 获取每个用户在每个显卡上的显存使用情况
    # PID -> User
    _, stdout, _ = client.exec_command("ps -eo user:100,pid")
    pid2user = {}
    for line in stdout.read().decode().splitlines()[1:]: # Skip the header
        user, pid = line.split()
        pid2user[pid] = user
    # GPU-UUID -> GPU-INDEX
    _, stdout, _ = client.exec_command("nvidia-smi --query-gpu=index,uuid --format=csv,noheader")
    uuid2cuda = {}
    for line in stdout.read().decode().splitlines():
        index, uuid = line.split(',')
        uuid2cuda[uuid] = f'cuda:{index}'
    # Memory -> PID & GPU-UUID
    _, stdout, _ = client.exec_command("nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits")
    record['cuda_per_user'] = []
    for line in stdout.read().decode().splitlines():
        pid, uuid, memory = line.split(',')
        cuda = uuid2cuda.get(uuid, 'UNKNOWN')
        user = pid2user.get(pid, f'PID{pid}')
        memory = int(memory)
        record['cuda_per_user'].append((cuda, user, memory))

    return record


def monitor_server(host, server_config, interval=30, save_path='./data'):
    os.makedirs(save_path, exist_ok=True)
    path = os.path.join(save_path, f'{host}.json')
    logger = getLogger(f'my.{host}')
    while True:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(**server_config)
            except Exception as e:
                logger.error(f"Failed to connect to {host}: {e}")
                return
            while True:
                record = get_stats(ssh)
                record['host'] = host
                with open(path, 'a') as f: f.write(json.dumps(record) + '\n')
                logger.debug(' | '.join([f"{k}: {v}" for k, v in record.items()]))
                time.sleep(interval)
        except Exception as e:
            time.sleep(60)
            logger.warning(str(e))
            pass


if __name__ == '__main__':
    set_logger('ServerMonitor', file='./log/monitor.log', basename='my')
    hosts = yaml.load(open('hosts.yml'), Loader=yaml.FullLoader)
    for host, config in hosts.items():
        threading.Thread(target=monitor_server, args=(host, config,)).start()
