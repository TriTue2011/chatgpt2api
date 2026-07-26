# -*- coding: utf-8 -*-
"""Pyscript SERVICE: ghi automation do AI sinh vao automations.yaml — co BACKUP
truoc khi ghi + FLOCK chan 2 luot tao automation chay song song lam xen ke
(interleave) hong CA file (khong chi 1 block). Pyscript CAM 'open' trong event
loop VA tu choi moi ham do pyscript dinh nghia (ke ca trong modules/) khi dua
vao task.executor → CHI dua ham STDLIB (os.open/os.close, fcntl.flock,
os.path.isfile, shutil.copy2, Path.read_bytes/write_bytes...) vao executor,
dung y het ai_file_ops.py; branching chay thang trong service function (khong
dung generator expression/comprehension — pyscript khong ho tro).
"""
import fcntl
import os
import shutil
import time
from pathlib import Path

AUTOMATIONS_PATH = "/config/automations.yaml"
BACKUP_DIR = "/config/ai_backups"


@service
def create_automation_by_ai(message=None):
    if not message:
        return
    path = AUTOMATIONS_PATH
    # Ghi thuan Python, KHONG qua shell (ban cu dung subprocess shell=True voi
    # message do AI sinh chua dau nhay/;/$() la SHELL INJECTION ngay trong
    # container HA). flock ca file trong suot read-modify-write: chan 2 luot
    # tao automation song song ghi xen ke lam hong CA file (khong chi mat 1
    # block cua rieng minh).
    fd = task.executor(os.open, path, os.O_RDWR | os.O_CREAT, 0o644)
    task.executor(fcntl.flock, fd, fcntl.LOCK_EX)
    try:
        exists = task.executor(os.path.isfile, path)
        if exists:
            task.executor(os.makedirs, BACKUP_DIR, exist_ok=True)
            bak = os.path.join(
                BACKUP_DIR,
                path.replace("/", "_").strip("_") + "." + str(int(time.time())) + ".bak",
            )
            task.executor(shutil.copy2, path, bak)
            raw = task.executor(Path(path).read_bytes)
        else:
            raw = b""
        new_raw = raw + ("\n" + str(message) + "\n").encode("utf-8")
        task.executor(Path(path).write_bytes, new_raw)
    finally:
        task.executor(fcntl.flock, fd, fcntl.LOCK_UN)
        task.executor(os.close, fd)

    # Reload automations
    automation.reload()
