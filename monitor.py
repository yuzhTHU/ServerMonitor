import os
import time
import json
import paramiko
import threading
from logging import getLogger
from logger import set_logger
import yaml


def get_cpu_stats(client):
    record = {}
    # 获取CPU使用率和总核数
    _, stdout, _ = client.exec_command("top -b -n 3 -d 1 | grep 'Cpu(s)' | tail -n1")
    record['cpu'] = float(stdout.read().decode().split()[1])
    _, stdout, _ = client.exec_command("nproc")
    record['cpu_free'] = int(stdout.read().decode().strip()) * (1 - record['cpu'] / 100)

    # 获取系统上各个用户的 CPU 使用情况
    _, stdout, _ = client.exec_command("ps -eo user:100,%cpu | awk 'NR > 1 {cpu[$1] += $2} END {for (u in cpu) print u, cpu[u]}' | sort -k2 -nr")
    record['cpu_per_user'] = []
    for line in stdout.read().decode().splitlines(): # Skip the header
        user, cpu_usage = line.split()
        record['cpu_per_user'].append((user, float(cpu_usage)))
    # 应当有 sum(usage for user, usage in record['cpu_per_user']) ~ record['cpu'] * record['cpu-free'] / (1 - record['cpu'] / 100)

    return record


def get_memory_stats(client):
    record = {}
    # 获取内存使用率和总内存
    _, stdout, _ = client.exec_command("free -m | awk 'NR==2{print $3/$2*100, $7}'")
    record['memory'], record['memory_free'] = stdout.read().decode().strip().split()
    record['memory'], record['memory_free'] = float(record['memory']), float(record['memory_free'])

    # 获取系统上各个用户的内存使用情况
    _, stdout, _ = client.exec_command("ps -eo user:100,%mem | awk 'NR > 1 {mem[$1] += $2} END {for (u in mem) print u, mem[u]}' | sort -k2 -nr")
    record['memory_per_user'] = []
    for line in stdout.read().decode().splitlines():  # Skip the header
        user, memory_usage = line.split()
        record['memory_per_user'].append((user, float(memory_usage)))
    # 应当有 sum(usage for user, usage in record['memory_per_user']) ~ record['memory']

    return record


def get_cuda_stats(client):
    record = {}
    # 检查是否有失效的GPU（Unable to determine the device handle for gpu 0000:0A:00.0: Unknown Error）
    _, stdout, _ = client.exec_command("nvidia-smi -L")
    result = stdout.read().decode()
    if 'Unable to determine the device handle for gpu' in result:
        valid = []
        for idx, row in enumerate(result.strip().split('\n')):
            if 'Unable to determine the device handle for gpu' not in row: 
                valid.append(row.split(':')[0].split(' ')[1])
        valid = ' --id=' + ','.join(valid)
    else:
        valid = ''
        
    # 获取每个GPU的显存使用情况和总显存
    _, stdout, _ = client.exec_command("nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits" + valid)
    indexes, memory_useds, memory_totals = [], [], []
    for gpu in stdout.read().decode().strip().split('\n'):
        index, memory_used, memory_total = gpu.split(',')
        indexes.append(int(index))
        memory_useds.append(float(memory_used))
        memory_totals.append(float(memory_total))
    record['cuda'] = [0] * (max(indexes) + 1)
    record['cuda-free'] = [0] * (max(indexes) + 1)
    for index, memory_used, memory_total in zip(indexes, memory_useds, memory_totals):
        record['cuda'][index] = memory_used / memory_total * 100
        record['cuda-free'][index] = memory_total - memory_used

    # 获取每个用户在每个显卡上的显存使用情况
    # PID -> User
    _, stdout, _ = client.exec_command("ps -eo user:100,pid")
    pid2user = {}
    for line in stdout.read().decode().splitlines()[1:]: # Skip the header
        user, pid = line.split()
        pid2user[pid] = user
    # GPU-UUID -> GPU-INDEX
    _, stdout, _ = client.exec_command("nvidia-smi --query-gpu=index,uuid --format=csv,noheader" + valid)
    uuid2cuda = {}
    for line in stdout.read().decode().splitlines():
        index, uuid = line.split(',')
        uuid2cuda[uuid] = f'cuda:{index}'
    # Memory -> PID & GPU-UUID
    _, stdout, _ = client.exec_command("nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits" + valid)
    record['cuda_per_user'] = []
    for line in stdout.read().decode().splitlines():
        pid, uuid, memory = line.split(',')
        cuda = uuid2cuda.get(uuid, 'UNKNOWN')
        user = pid2user.get(pid, f'PID{pid}')
        memory = int(memory)
        record['cuda_per_user'].append((cuda, user, memory))
    # 应当有 
    # cuda_usage = np.zeros(len(record['cuda']))
    # for device, user, usage in record['cuda_per_user']:
    #     cuda_usage[int(device.split(':')[1])] += usage
    # (100 * cuda_usage / np.array(record['cuda-free']) * (1 - np.array(record['cuda']) / 100)).tolist() ~ record['cuda']
    return record


def get_stats(client, save=False):
    record = dict(timestamp=time.time())
    record.update(get_cpu_stats(client))
    record.update(get_memory_stats(client))
    record.update(get_cuda_stats(client))
    return record


def monitor_server(host, server_config, interval=30, save_path='./data', patience=10):
    os.makedirs(save_path, exist_ok=True)
    path = os.path.join(save_path, f'{host}.json')
    logger = getLogger(f'my.{host}')
    cnt = patience
    while cnt > 0:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(**server_config)
        cnt = patience
        try:
            while True:
                record = get_stats(ssh)
                record['host'] = host
                with open(path, 'a') as f: f.write(json.dumps(record) + '\n')
                logger.debug(' | '.join([f"{k}: {v}" for k, v in record.items()]))
                time.sleep(interval)
        except Exception as e:
            cnt -= 1
            time.sleep(60)
            logger.error(f"Failed to connect to {host}: {e}")


if __name__ == '__main__':
    set_logger('ServerMonitor', file='./log/monitor.log', basename='my')
    hosts = yaml.load(open('hosts.yml'), Loader=yaml.FullLoader)
    for host, config in hosts.items():
        threading.Thread(target=monitor_server, args=(host, config,)).start()
