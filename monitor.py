import os
import yaml
import time
import json
import dotenv
import threading
import traceback
from logging import getLogger
from src.logger import set_logger
from src.ssh_connect import ssh_connect
from src.monitor import get_cpu_stats, get_memory_stats, get_cuda_stats

dotenv.load_dotenv()


def monitor_server(host, server_config, interval=30, save_path='./data', patience=10):
    os.makedirs(save_path, exist_ok=True)
    path = os.path.join(save_path, f'{host}.json')
    logger = getLogger(f'my.{host}')
    cnt = patience
    while cnt > 0:
        try:
            ssh = ssh_connect(server_config)
            cnt = patience
            while True:
                record = dict(timestamp=time.time())
                record.update(get_cpu_stats(ssh))
                record.update(get_memory_stats(ssh))
                try:
                    record.update(get_cuda_stats(ssh))
                except Exception as e:
                    record.update({'cuda': [], 'cuda-free': [], 'cuda_per_user': []})
                    logger.error(
                        f"Failed to get CUDA stats in {host}: "
                        f"[{type(e)}] {e}\n"
                        f"{traceback.format_exc()}"
                    )
                record['host'] = host
                with open(path, 'a') as f: 
                    f.write(json.dumps(record) + '\n')
                logger.debug(' | '.join([f"{k}: {v}" for k, v in record.items()]))
                time.sleep(interval)
        except Exception as e:
            cnt -= 1
            logger.error(
                f"Failed to connect to {host}: "
                f"[{type(e)}] {e}\n"
                f"{traceback.format_exc()}"
            )
            time.sleep(60)


if __name__ == '__main__':
    set_logger('ServerMonitor', file='./log/monitor.log', basename='my')
    hosts = yaml.load(open('hosts.yml'), Loader=yaml.FullLoader)
    # monitor_server('spark03', hosts['spark03'])
    for host, config in hosts.items():
        threading.Thread(target=monitor_server, args=(host, config,)).start()
