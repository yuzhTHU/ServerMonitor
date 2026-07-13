from ..ssh_connect import safe_exec_command


def get_cpu_stats(client):
    record = {}
    # 获取CPU使用率和总核数
    nproc = int(safe_exec_command(client, "nproc").strip())
    record['cpu_total_millicores'] = nproc * 1000

    # CPU usage: same measurement as legacy — take `us` (user-mode CPU %)
    # from top's 3rd sample.  LANG=C ensures predictable column layout.
    result = safe_exec_command(client, "LANG=C top -b -n 3 -d 1 | grep '%Cpu' | tail -n1")
    # "%Cpu(s):  0.4 us,  0.1 sy,  ..." → split()[1] = us value
    us_pct = float(result.split()[1])
    record['cpu_usage_millicores'] = round(us_pct / 100 * nproc * 1000)

    # 获取系统上各个用户的 CPU 使用情况
    result = safe_exec_command(client, "ps -eo user:100,%cpu | awk 'NR>1 {cpu[$1]+=$2} END {for(u in cpu) print u, cpu[u]}'")
    record['cpu_per_user'] = {}
    for line in result.splitlines():
        line = line.strip()
        if not line:
            continue
        user, cpu_pct_sum = line.rsplit(' ', 1) if ' ' in line else (line, '0')
        record['cpu_per_user'][user] = int(round(float(cpu_pct_sum) * 10))

    return record
