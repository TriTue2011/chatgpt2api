# -*- coding: utf-8 -*-
"""Pyscript SERVICE: doc/ghi/restore file config HA cho AI gateway (backup +
whitelist). Pyscript CAM 'open' trong event loop VA tu choi moi ham do pyscript
dinh nghia (ke ca trong modules/) khi dua vao task.executor → chi dua ham STDLIB
(Path.read_bytes/write_bytes, os.path.isfile, shutil.copy2...) vao executor;
branching/base64 chay thang. Cai /config/pyscript/ + pyscript.reload.
"""
import base64
import os
import shutil
import time
from pathlib import Path

ALLOW_PREFIXES = ("/config/blueprints/", "/config/packages/")
ALLOW_FILES = ("/config/configuration.yaml",)
BACKUP_DIR = "/config/ai_backups"


def _norm(path):
    # Pyscript KHONG ho tro generator expression/comprehension → dung vong lap.
    p = os.path.normpath(str(path or ""))
    if not p.startswith("/config/") or ".." in p:
        return None
    allowed = p in ALLOW_FILES
    if not allowed:
        for pre in ALLOW_PREFIXES:
            if p.startswith(pre):
                allowed = True
                break
    return p if allowed else None


@service(supports_response="only")
def ai_file_ops(op=None, path=None, content_b64=None):
    """yaml
name: AI file ops
description: Read/write/restore HA config files for the AI gateway (with backup).
fields:
  op:
    description: read | write | restore | exists
    required: true
  path:
    description: absolute path under /config (whitelisted)
    required: true
  content_b64:
    description: base64 UTF-8 content (op=write)
    required: false
"""
    p = _norm(path)
    if not p:
        return {"ok": False, "error": "path khong duoc phep: " + str(path)}
    op = str(op or "").lower()
    try:
        if op == "exists":
            return {"ok": True, "exists": task.executor(os.path.isfile, p)}
        if op == "read":
            if not task.executor(os.path.isfile, p):
                return {"ok": True, "exists": False, "content_b64": ""}
            raw = task.executor(Path(p).read_bytes)
            return {"ok": True, "exists": True, "content_b64": base64.b64encode(raw).decode()}
        if op == "write":
            raw = base64.b64decode(str(content_b64 or ""))
            bak = ""
            if task.executor(os.path.isfile, p):
                task.executor(os.makedirs, BACKUP_DIR, exist_ok=True)
                bak = os.path.join(BACKUP_DIR, p.replace("/", "_").strip("_") + "." + str(int(time.time())) + ".bak")
                task.executor(shutil.copy2, p, bak)
            d = os.path.dirname(p)
            if d:
                task.executor(os.makedirs, d, exist_ok=True)
            task.executor(Path(p).write_bytes, raw)
            return {"ok": True, "backup": bak, "bytes": len(raw)}
        if op == "restore":
            if not task.executor(os.path.isdir, BACKUP_DIR):
                return {"ok": False, "error": "khong co backup dir"}
            key = p.replace("/", "_").strip("_") + "."
            names = task.executor(os.listdir, BACKUP_DIR)
            cands = []
            for x in names:
                if x.startswith(key) and x.endswith(".bak"):
                    cands.append(x)
            cands.sort()
            if not cands:
                return {"ok": False, "error": "khong co backup"}
            src = os.path.join(BACKUP_DIR, cands[-1])
            task.executor(shutil.copy2, src, p)
            return {"ok": True, "restored_from": src}
        return {"ok": False, "error": "op khong hop le: " + op}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}
