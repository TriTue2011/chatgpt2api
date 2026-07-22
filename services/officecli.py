"""OfficeCLI runner — native in-process for c2a agent (no external MCP required).

Uses the `officecli` binary (bundled in Docker image). All document paths are
sandboxed under DATA_DIR/office (default /app/data/office).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_CMDS = frozenset({
    "create", "view", "get", "query", "set", "add", "remove", "move", "swap",
    "validate", "batch", "merge", "dump", "open", "close", "save", "help",
    "import", "refresh",
})

_TIMEOUT_DEFAULT = 60
_TIMEOUT_LONG = 180
_MAX_OUT = 80_000
_OFFICE_EXT = (".docx", ".xlsx", ".pptx")


def bin_path() -> str | None:
    env = (os.environ.get("OFFICECLI_BIN") or "").strip()
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    found = shutil.which("officecli")
    if found:
        return found
    for candidate in ("/usr/local/bin/officecli", "/opt/officecli/officecli"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def is_available() -> bool:
    return bin_path() is not None


def workspace() -> Path:
    try:
        from services.config import DATA_DIR
        base = Path(DATA_DIR)
    except Exception:
        base = Path(os.environ.get("OFFICECLI_WORKSPACE") or "/app/data/office").parent
    raw = (os.environ.get("OFFICECLI_WORKSPACE") or "").strip()
    p = Path(raw).resolve() if raw else (base / "office").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_path(user_path: str, *, must_exist: bool = False) -> Path:
    ws = workspace()
    raw = (user_path or "").strip()
    if not raw:
        raise ValueError("path rỗng")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (ws / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(ws)
    except ValueError as exc:
        raise ValueError(f"Path phải trong workspace {ws}") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Không thấy file: {candidate}")
    return candidate


def run(args: list[str], *, timeout: int = _TIMEOUT_DEFAULT) -> str:
    binary = bin_path()
    if not binary:
        return (
            "OfficeCLI chưa có trong container. Rebuild image c2a (Dockerfile "
            "cài binary) hoặc set OFFICECLI_BIN."
        )
    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(workspace()),
            env={**os.environ, "OFFICECLI_SKIP_UPDATE": "1"},
        )
    except subprocess.TimeoutExpired:
        return f"Timeout sau {timeout}s"
    except Exception as exc:
        logger.warning("officecli: %s", exc)
        return f"Lỗi officecli: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return f"officecli error ({proc.returncode}): {(err or out)[:4000]}"
    text = out if out else (err or "OK")
    return text if len(text) <= _MAX_OUT else text[:_MAX_OUT] + "\n…[truncated]"


def status() -> dict[str, Any]:
    binary = bin_path()
    ws = workspace()
    ver = run(["--version"], timeout=15) if binary else ""
    files = sorted(p.name for p in ws.iterdir() if p.is_file() and p.suffix.lower() in _OFFICE_EXT)[:80]
    return {
        "ok": bool(binary),
        "binary": binary,
        "version": (ver.splitlines()[0] if ver and binary else None),
        "workspace": str(ws),
        "files": files,
    }


def create(filename: str) -> dict[str, Any]:
    path = resolve_path(filename)
    if path.suffix.lower() not in _OFFICE_EXT:
        return {"ok": False, "text": "Chỉ hỗ trợ .docx, .xlsx, .pptx"}
    if path.exists():
        return {
            "ok": True,
            "text": f"File đã có: {path.name}",
            "file_path": str(path),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    msg = run(["create", str(path)], timeout=30)
    return {
        "ok": path.exists(),
        "text": f"{msg}\nĐã tạo: {path.name}",
        "file_path": str(path) if path.exists() else None,
    }


def view(path: str, mode: str = "outline") -> str:
    mode = (mode or "outline").strip().lower()
    if mode not in ("outline", "text", "annotated", "stats", "issues"):
        mode = "outline"
    p = resolve_path(path, must_exist=True)
    return run(["view", str(p), mode])


def get(path: str, element_path: str = "/", depth: int = 2) -> str:
    p = resolve_path(path, must_exist=True)
    d = max(0, min(int(depth or 2), 5))
    return run(["get", str(p), element_path or "/", "--depth", str(d), "--json"])


def query(path: str, selector: str) -> str:
    p = resolve_path(path, must_exist=True)
    return run(["query", str(p), (selector or "").strip(), "--json"])


def set_props(path: str, element_path: str, props: dict) -> str:
    p = resolve_path(path, must_exist=True)
    if not isinstance(props, dict) or not props:
        return "props phải là object không rỗng"
    args = ["set", str(p), element_path or "/"]
    for k, v in props.items():
        if not re.match(r"^[A-Za-z0-9_.-]+$", str(k)):
            return f"prop không hợp lệ: {k}"
        args.extend(["--prop", f"{k}={v}"])
    args.append("--json")
    return run(args)


def add(path: str, parent_path: str, type_name: str, props: dict | None = None) -> str:
    p = resolve_path(path, must_exist=True)
    t = (type_name or "").strip()
    if not t or not re.match(r"^[A-Za-z0-9_-]+$", t):
        return "type_name không hợp lệ"
    args = ["add", str(p), parent_path or "/", "--type", t]
    for k, v in (props or {}).items():
        if not re.match(r"^[A-Za-z0-9_.-]+$", str(k)):
            return f"prop không hợp lệ: {k}"
        args.extend(["--prop", f"{k}={v}"])
    args.append("--json")
    return run(args)


def remove(path: str, element_path: str) -> str:
    p = resolve_path(path, must_exist=True)
    return run(["remove", str(p), (element_path or "").strip(), "--json"])


def merge(template_path: str, output_filename: str, data: dict) -> dict[str, Any]:
    src = resolve_path(template_path, must_exist=True)
    out = resolve_path(output_filename)
    if not isinstance(data, dict):
        return {"ok": False, "text": "data phải là object"}
    data_file = workspace() / f".merge_{os.getpid()}.json"
    try:
        data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        msg = run(["merge", str(src), str(out), "--data", str(data_file)], timeout=_TIMEOUT_LONG)
    finally:
        try:
            data_file.unlink(missing_ok=True)
        except Exception:
            pass
    return {
        "ok": out.exists(),
        "text": f"{msg}\nOutput: {out.name}",
        "file_path": str(out) if out.exists() else None,
    }


def batch(path: str, commands: list, *, best_effort: bool = False) -> str:
    p = resolve_path(path, must_exist=True)
    if not isinstance(commands, list) or not commands:
        return "commands phải là array không rỗng"
    batch_file = workspace() / f".batch_{os.getpid()}.json"
    try:
        batch_file.write_text(json.dumps(commands, ensure_ascii=False), encoding="utf-8")
        args = ["batch", str(p), "--input", str(batch_file), "--json"]
        if best_effort:
            args.append("--best-effort")
        return run(args, timeout=_TIMEOUT_LONG)
    finally:
        try:
            batch_file.unlink(missing_ok=True)
        except Exception:
            pass


def validate(path: str) -> str:
    p = resolve_path(path, must_exist=True)
    v = run(["validate", str(p)])
    issues = run(["view", str(p), "issues", "--json"])
    return f"=== validate ===\n{v}\n\n=== issues ===\n{issues}"


def list_files() -> list[dict[str, Any]]:
    ws = workspace()
    items = []
    for p in sorted(ws.rglob("*")):
        if p.is_file() and p.suffix.lower() in _OFFICE_EXT:
            items.append({"path": str(p.relative_to(ws)), "bytes": p.stat().st_size})
    return items[:200]


def parse_props(props_json: str | dict | None) -> dict:
    if isinstance(props_json, dict):
        return props_json
    if not props_json:
        return {}
    try:
        d = json.loads(str(props_json))
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}
