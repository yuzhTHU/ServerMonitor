import re
import os
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import timedelta


class LogFormatter(logging.Formatter):
    color_dict = {
        'DEBUG': '\033[0;37m{}\033[0m',
        'INFO': '\033[0;34m{}\033[0m',
        'NOTE': '\033[0;33m{}\033[0m',
        'WARNING': '\033[0;33m{}\033[0m',
        'ERROR': '\033[0;31m{}\033[0m',
        'CRITICAL': '\033[0;35m{}\033[0m',
    }

    def __init__(self, name, colorful=False, start_time=None):
        super().__init__()
        self.name = name
        self.colorful = colorful
        self.start_time = start_time or time.time()

    def format(self, record):
        duration = round(record.created - self.start_time)
        prefixes = [
            self.name,
            record.name.split('.')[-1],
            record.levelname[0],
            time.strftime('%Y%m%d%H%M%S'),
            str(timedelta(seconds=duration)),
        ]
        if record.levelname in ['WARNING', 'ERROR', 'CRITICAL']:
            prefixes.append(f"{record.filename}:{record.lineno}")
        prefix = f"[{'|'.join(prefixes)}] "
        message = record.getMessage() or ''
        message = message.replace('\n', '\n' + ' '*len(prefix))
        if self.colorful:
            return self.color_dict.get(record.levelname, '{}').format(prefix) + message
        else:
            return prefix + re.sub(r'\033\[\d+;?\d*m', '', message)


def set_logger(name, file=None, quiet=False, basename='my'):
    """
    运行一次 set_logger 后，可以通过 logging.getLogger('{basename}.{xxx}') 获取 logger, 
    与这里设置的 logger 具有相同的 Handler 和 Formatter
    """
    start_time = time.time()
    logging.addLevelName(30, "NOTE")
    def note(self, message, *args, **kwargs):
        if self.isEnabledFor(30):
            self._log(30, message, args, **kwargs)
    logging.Logger.note = note

    logger = logging.getLogger(basename)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers = []

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING if quiet else logging.INFO)
    console_handler.setFormatter(LogFormatter(name, colorful=True, start_time=start_time))
    logger.addHandler(console_handler)

    if file is not None:
        os.makedirs(os.path.dirname(file), exist_ok=True)
        file_handler = RotatingFileHandler(file, mode='a', maxBytes=50*1024*1024, backupCount=100)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(LogFormatter(name, colorful=False, start_time=start_time))
        logger.addHandler(file_handler)
