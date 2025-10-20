from ..ssh_connect import safe_exec_command


def get_memory_stats(client):
    record = {}
    # 获取内存使用率和总内存
    result = safe_exec_command(client, "free -m | awk 'NR==2{print $3/$2*100, $7}'")
    record['memory'], record['memory_free'] = result.strip().split()
    record['memory'], record['memory_free'] = float(record['memory']), float(record['memory_free'])

    # 获取系统上各个用户的内存使用情况
    result = safe_exec_command(client, "ps -eo user:100,%mem | awk 'NR > 1 {mem[$1] += $2} END {for (u in mem) print u, mem[u]}' | sort -k2 -nr")
    record['memory_per_user'] = []
    for line in result.splitlines():  # Skip the header
        user, memory_usage = line.split()
        record['memory_per_user'].append((user, float(memory_usage)))
    # 应当有 sum(usage for user, usage in record['memory_per_user']) ~ record['memory']

    return record
