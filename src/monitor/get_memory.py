# Copyright (c) 2024-present, Yumeow. Licensed under the MIT License.
from ..utils.ssh_connect import safe_exec_command


def get_memory_stats(client):
    record = {}
    # 获取内存使用率和总内存
    result = safe_exec_command(client, "grep MemTotal /proc/meminfo | awk '{print $2}'")
    mem_total_bytes = int(result.strip()) * 1024
    record['memory_total_bytes'] = mem_total_bytes

    result = safe_exec_command(client, "grep MemAvailable /proc/meminfo | awk '{print $2}'")
    mem_avail_bytes = int(result.strip()) * 1024
    record['memory_usage_bytes'] = mem_total_bytes - mem_avail_bytes

    # 获取系统上各个用户的内存使用情况
    result = safe_exec_command(client, "ps -eo user:100,rss | awk 'NR>1 {mem[$1]+=$2} END {for(u in mem) print u, mem[u]}'")
    record['memory_per_user'] = {}
    for line in result.splitlines():
        line = line.strip()
        if not line:
            continue
        user, rss_kb = line.rsplit(' ', 1) if ' ' in line else (line, '0')
        record['memory_per_user'][user] = int(rss_kb) * 1024

    return record
