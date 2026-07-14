# Copyright (c) 2024-present, Yumeow. Licensed under the MIT License.
import json
from ..utils.ssh_connect import safe_exec_command


def get_cuda_stats(client):
    record = {}
    # 检查是否有GPU
    result = safe_exec_command(client, "lspci | grep -i nvidia")
    if not result.strip():
        return {
            'gpu_usage_bytes': '{}',
            'gpu_total_bytes': '{}',
            'gpu_per_user': '{}',
        }

    # 检查是否有失效的GPU（Unable to determine the device handle for gpu 0000:0A:00.0: Unknown Error）
    result = safe_exec_command(client, "nvidia-smi -L")
    if 'Unable to determine the device handle for gpu' in result:
        valid = []
        for row in result.strip().split('\n'):
            if 'Unable to determine the device handle for gpu' not in row:
                valid.append(row.split(':')[0].split(' ')[1])
        valid_flag = ' --id=' + ','.join(valid) if valid else ''
    else:
        valid_flag = ''

    # 获取每个GPU的显存使用情况和总显存
    result = safe_exec_command(client, "nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits" + valid_flag)
    gpu_usage_bytes = {}
    gpu_total_bytes = {}
    for gpu_line in result.strip().split('\n'):
        gpu_line = gpu_line.strip()
        if not gpu_line:
            continue
        index, mem_used_mib, mem_total_mib = gpu_line.split(',')
        gpu_id = f'cuda:{index.strip()}'
        gpu_usage_bytes[gpu_id] = int(mem_used_mib.strip()) * 1048576
        gpu_total_bytes[gpu_id] = int(mem_total_mib.strip()) * 1048576

    record['gpu_usage_bytes'] = json.dumps(gpu_usage_bytes)
    record['gpu_total_bytes'] = json.dumps(gpu_total_bytes)

    # 获取每个用户在每个显卡上的显存使用情况
    # PID -> User
    result = safe_exec_command(client, "ps -eo user:100,pid")
    pid2user = {}
    for line in result.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(' ', 1) if ' ' in line else (line, '?')
        if len(parts) != 2:
            continue
        user, pid = parts
        pid2user[pid] = user
    # GPU-UUID -> GPU-INDEX
    result = safe_exec_command(client, "nvidia-smi --query-gpu=index,uuid --format=csv,noheader" + valid_flag)
    uuid2gpu = {}
    for line in result.splitlines():
        line = line.strip()
        if not line:
            continue
        index, uuid = line.split(',')
        uuid2gpu[uuid.strip()] = f'cuda:{index.strip()}'

    # Memory -> PID & GPU-UUID
    result = safe_exec_command(client, "nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits" + valid_flag)
    gpu_per_user = {}
    for line in result.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid, uuid, mem_mib = line.split(',')
        except ValueError:
            continue
        gpu_id = uuid2gpu.get(uuid.strip(), 'UNKNOWN')
        user = pid2user.get(pid.strip(), f'PID{pid.strip()}')
        mem_bytes = int(mem_mib.strip()) * 1048576

        if user not in gpu_per_user:
            gpu_per_user[user] = {}
        gpu_per_user[user][gpu_id] = gpu_per_user[user].get(gpu_id, 0) + mem_bytes

    record['gpu_per_user'] = json.dumps(gpu_per_user, ensure_ascii=False)

    return record
