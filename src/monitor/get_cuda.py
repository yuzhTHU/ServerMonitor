from ..ssh_connect import safe_exec_command


def get_cuda_stats(client):
    record = {}
    # 检查是否有GPU
    result = safe_exec_command(client, "lspci | grep -i nvidia")
    if not result:
        return {'cuda': [], 'cuda-free': [], 'cuda_per_user': []}

    # 检查是否有失效的GPU（Unable to determine the device handle for gpu 0000:0A:00.0: Unknown Error）
    result = safe_exec_command(client, "nvidia-smi -L")
    if 'Unable to determine the device handle for gpu' in result:
        valid = []
        for idx, row in enumerate(result.strip().split('\n')):
            if 'Unable to determine the device handle for gpu' not in row: 
                valid.append(row.split(':')[0].split(' ')[1])
        valid = ' --id=' + ','.join(valid)
    else:
        valid = ''
        
    # 获取每个GPU的显存使用情况和总显存
    result = safe_exec_command(client, "nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits" + valid)
    indexes, memory_useds, memory_totals = [], [], []
    for gpu in result.strip().split('\n'):
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
    result = safe_exec_command(client, "ps -eo user:100,pid")
    pid2user = {}
    for line in result.splitlines()[1:]: # Skip the header
        user, pid = line.split()
        pid2user[pid] = user
    # GPU-UUID -> GPU-INDEX
    result = safe_exec_command(client, "nvidia-smi --query-gpu=index,uuid --format=csv,noheader" + valid)
    uuid2cuda = {}
    for line in result.splitlines():
        index, uuid = line.split(',')
        uuid2cuda[uuid] = f'cuda:{index}'
    # Memory -> PID & GPU-UUID
    result = safe_exec_command(client, "nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits" + valid)
    record['cuda_per_user'] = []
    for line in result.splitlines():
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
