from ..ssh_connect import safe_exec_command


def get_cpu_stats(client):
    record = {}
    # 获取CPU使用率和总核数
    result = safe_exec_command(client, "top -b -n 3 -d 1 | grep 'Cpu(s)' | tail -n1")
    record['cpu'] = float(result.split()[1])
    result = safe_exec_command(client, "nproc")
    record['cpu_free'] = int(result.strip()) * (1 - record['cpu'] / 100)

    # 获取系统上各个用户的 CPU 使用情况
    result = safe_exec_command(client, "ps -eo user:100,%cpu | awk 'NR > 1 {cpu[$1] += $2} END {for (u in cpu) print u, cpu[u]}' | sort -k2 -nr")
    record['cpu_per_user'] = []
    for line in result.splitlines(): # Skip the header
        user, cpu_usage = line.split()
        record['cpu_per_user'].append((user, float(cpu_usage)))
    # 应当有 sum(usage for user, usage in record['cpu_per_user']) ~ record['cpu'] * record['cpu-free'] / (1 - record['cpu'] / 100)

    return record
