# Copyright (c) 2024-present, Yumeow. Licensed under the MIT License.
import os
import json
import sqlite3
import threading
import time
import traceback
from logging import getLogger
from pathlib import Path

import yaml

from src.monitor import get_cpu_stats, get_memory_stats, get_cuda_stats
from src.utils.logger import set_logger
from src.utils.ssh_connect import ssh_connect

DATA_DIR = './data'
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.getenv('CONFIG_DIR', BASE_DIR / 'config'))

CREATE_SNAPSHOTS_TABLE = '''
CREATE TABLE IF NOT EXISTS snapshots (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    host                  TEXT NOT NULL,
    timestamp             INTEGER NOT NULL,
    cpu_usage_millicores  INTEGER NOT NULL,
    cpu_total_millicores  INTEGER NOT NULL,
    memory_usage_bytes    INTEGER NOT NULL,
    memory_total_bytes    INTEGER NOT NULL,
    gpu_usage_bytes       TEXT NOT NULL DEFAULT '{}',
    gpu_total_bytes       TEXT NOT NULL DEFAULT '{}',
    cpu_per_user          TEXT NOT NULL DEFAULT '{}',
    memory_per_user       TEXT NOT NULL DEFAULT '{}',
    gpu_per_user          TEXT NOT NULL DEFAULT '{}',
    UNIQUE(host, timestamp)
)
'''

CREATE_INDEX = '''
CREATE INDEX IF NOT EXISTS idx_snapshots_host_ts
ON snapshots(host, timestamp)
'''

INSERT_SQL = '''
INSERT OR REPLACE INTO snapshots
    (host, timestamp,
     cpu_usage_millicores, cpu_total_millicores,
     memory_usage_bytes, memory_total_bytes,
     gpu_usage_bytes, gpu_total_bytes,
     cpu_per_user, memory_per_user, gpu_per_user)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
'''


def get_db_path(host, timestamp=None, data_dir=DATA_DIR):
    if timestamp is None:
        timestamp = time.time()
    year = time.localtime(timestamp).tm_year
    return os.path.join(data_dir, host, f'{year}.db')


def init_db(host, timestamp=None, data_dir=DATA_DIR):
    db_path = get_db_path(host, timestamp, data_dir)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute(CREATE_SNAPSHOTS_TABLE)
    conn.execute(CREATE_INDEX)
    conn.commit()
    conn.close()
    return db_path


def monitor_server(host, server_config, interval=30, data_dir=DATA_DIR, patience=10):
    logger = getLogger(f'my.{host}')
    cnt = patience
    while cnt > 0:
        try:
            ssh = ssh_connect(server_config)
            cnt = patience
            current_db_path = None
            while True:
                record = dict(timestamp=int(time.time()))
                record.update(get_cpu_stats(ssh))
                record.update(get_memory_stats(ssh))
                try:
                    record.update(get_cuda_stats(ssh))
                except Exception as e:
                    record.update({
                        'gpu_usage_bytes': '{}',
                        'gpu_total_bytes': '{}',
                        'gpu_per_user': '{}',
                    })
                    logger.error(
                        f"Failed to get CUDA stats in {host}: "
                        f"[{type(e)}] {e}\n"
                        f"{traceback.format_exc()}"
                    )
                record['host'] = host

                # Serialize per-user dicts to JSON strings for SQLite
                record['cpu_per_user'] = json.dumps(record['cpu_per_user'], ensure_ascii=False)
                record['memory_per_user'] = json.dumps(record['memory_per_user'], ensure_ascii=False)

                db_path = get_db_path(host, record['timestamp'], data_dir)
                if db_path != current_db_path:
                    init_db(host, record['timestamp'], data_dir)
                    current_db_path = db_path

                conn = sqlite3.connect(db_path, timeout=30)
                try:
                    conn.execute(INSERT_SQL, (
                        record['host'], record['timestamp'],
                        record['cpu_usage_millicores'], record['cpu_total_millicores'],
                        record['memory_usage_bytes'], record['memory_total_bytes'],
                        record['gpu_usage_bytes'], record['gpu_total_bytes'],
                        record['cpu_per_user'], record['memory_per_user'], record['gpu_per_user'],
                    ))
                    conn.commit()
                finally:
                    conn.close()

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
    with open(CONFIG_DIR / 'hosts.yml', encoding='utf-8') as hosts_file:
        hosts = yaml.safe_load(hosts_file) or {}
    # monitor_server('spark03', hosts['spark03'])
    for host, config in hosts.items():
        init_db(host)
        threading.Thread(target=monitor_server, args=(host, config,)).start()
