# Copyright (c) 2024-present, Yumeow. Licensed under the MIT License.
import os
import platform
import subprocess
import re

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return "N/A"

def get_cpu_flags():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            flags_line = [line for line in f if 'flags' in line.lower()]
            if flags_line:
                flags = set(flags_line[0].strip().split(':')[1].split())
                return {
                    'avx': 'avx' in flags,
                    'avx2': 'avx2' in flags,
                    'avx512': any(f.startswith('avx512') for f in flags)
                }
    except (OSError, ValueError):
        return {}
    return {}

def get_cpu_counts():
    """获取物理核心数和逻辑线程数"""
    logical = os.cpu_count()
    physical = 0
    try:
        output = run_cmd("lscpu -p=core")
        if output != "N/A":
            # 去掉注释行
            cores = set()
            for line in output.splitlines():
                if line.startswith("#"):
                    continue
                cores.add(line.strip())
            physical = len(cores)
    except (OSError, ValueError):
        pass
    return physical if physical > 0 else "N/A", logical if logical else "N/A"

def get_cpu_freq():
    """读取当前 CPU 主频 (MHz)"""
    try:
        with open("/proc/cpuinfo") as f:
            freqs = [float(line.split(":")[1]) for line in f if "cpu MHz" in line]
            if freqs:
                return sum(freqs) / len(freqs)
    except (OSError, ValueError):
        return "N/A"
    return "N/A"

def get_memory_total():
    """读取内存总量 (GB)"""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024)
    except (OSError, ValueError):
        return "N/A"
    return "N/A"

def get_memory_channels():
    # Estimate memory channels using dmidecode
    try:
        output = run_cmd("sudo dmidecode -t memory")
        channels = len(re.findall(r"Locator: Channel", output))
        return "~{} (approx)" % channels
    except (OSError, subprocess.SubprocessError):
        return "N/A (requires root)"

def main():
    print("="*60)
    print("🔍 Server Hardware Info Summary")
    print("="*60)
    print("🖥️ Hostname        : {}".format(platform.node()))
    # 修复 CPU 型号提取语句
    cpu_model_cmd = "lscpu | grep 'Model name' | awk -F: '{print $2}'"
    print("🧠 CPU Model       : {}".format(run_cmd(cpu_model_cmd)))
    cores, threads = get_cpu_counts()
    print("🧵 Cores / Threads : {} C / {} T".format(cores, threads))
    freq = get_cpu_freq()
    print("⏱️ CPU Frequency   : {} MHz".format(round(freq, 2) if isinstance(freq, float) else freq))
    flags = get_cpu_flags()
    print("💡 SIMD Support    : AVX: {}, AVX2: {}, AVX-512: {}".format(flags.get('avx', False), flags.get('avx2', False), flags.get('avx512', False)))
    l3_cmd = "lscpu | grep 'L3 cache' | awk -F: '{print $2}'"
    print("📦 L3 Cache        : {}".format(run_cmd(l3_cmd)))
    numa_cmd = "lscpu | grep 'NUMA node(s)' | awk -F: '{print $2}'"
    print("🧩 NUMA Nodes      : {}".format(run_cmd(numa_cmd)))
    print("💽 Memory Total    : {} GB".format(get_memory_total()))
    # print(f"📚 Memory Channels : {get_memory_channels()}")
    print("💻 OS Version      : {}".format(platform.platform()))
    print("🐍 Python Version  : {}".format(platform.python_version()))

    print("="*60)
    #print("Tip: For best performance, bind processes to NUMA nodes using `numactl` if multi-socket.")
    #print("="*60)


if __name__ == "__main__":
    main()
