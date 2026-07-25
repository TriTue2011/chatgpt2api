from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from services.storage.base import StorageBackend


# Cross-platform file lock helper
class _FileLock:
    """Simple file-based lock for cross-platform concurrent access safety.
    
    Uses fcntl on Unix and msvcrt on Windows. Falls back to threading lock
    when neither is available.
    """
    
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._lock_fd = None
        self._thread_lock = threading.Lock()
        
        # Create lock file if it doesn't exist
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if not lock_path.exists():
            lock_path.touch()
    
    def _acquire_os_lock(self) -> bool:
        """Acquire OS-level file lock."""
        try:
            # Try fcntl (Unix/Linux/macOS)
            import fcntl
            self._lock_fd = open(self.lock_path, 'r')
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (ImportError, OSError):
            pass
        
        try:
            # Try msvcrt (Windows)
            import msvcrt
            self._lock_fd = open(self.lock_path, 'r+')
            msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (ImportError, OSError):
            pass
        
        return False
    
    def _release_os_lock(self) -> None:
        """Release OS-level file lock."""
        if self._lock_fd is None:
            return
        
        try:
            import fcntl
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
            self._lock_fd.close()
        except (ImportError, OSError):
            try:
                import msvcrt
                msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                self._lock_fd.close()
            except (ImportError, OSError):
                try:
                    self._lock_fd.close()
                except Exception:
                    pass
        
        self._lock_fd = None
    
    def acquire(self) -> None:
        """Acquire the file lock (blocking)."""
        acquired = self._acquire_os_lock()
        if not acquired:
            # Fallback to thread lock only
            self._thread_lock.acquire()
    
    def release(self) -> None:
        """Release the file lock."""
        if self._lock_fd is not None:
            self._release_os_lock()
        else:
            self._thread_lock.release()


class JSONStorageBackend(StorageBackend):
    """本地 JSON 文件存储后端 với file locking cho concurrent access safety."""

    def __init__(self, file_path: Path, auth_keys_path: Path | None = None):
        self.file_path = file_path
        self.auth_keys_path = auth_keys_path or file_path.with_name("auth_keys.json")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create per-file locks for thread-safe concurrent access
        self._file_lock = _FileLock(file_path.with_name(f".{file_path.name}.lock"))
        self._auth_lock = _FileLock(auth_keys_path.with_name(f".{auth_keys_path.name}.lock") if auth_keys_path else file_path.with_name(".auth_keys.json.lock"))

    @staticmethod
    def _load_json_list(file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, Exception):
            return []

    @staticmethod
    def _save_json_list(file_path: Path, items: list[dict[str, Any]]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp file then rename
        tmp_path = file_path.with_suffix('.tmp')
        tmp_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # Atomic rename (works on both Unix and Windows)
        os.replace(tmp_path, file_path)

    def load_accounts(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载账号数据 với file locking."""
        self._file_lock.acquire()
        try:
            return self._load_json_list(self.file_path)
        finally:
            self._file_lock.release()

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到 JSON 文件 với file locking."""
        self._file_lock.acquire()
        try:
            self._save_json_list(self.file_path, accounts)
        finally:
            self._file_lock.release()

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载鉴权密钥数据 voi file locking."""
        self._auth_lock.acquire()
        try:
            if not self.auth_keys_path.exists():
                return []
            try:
                data = json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                return []
            if isinstance(data, dict):
                data = data.get("items")
            return data if isinstance(data, list) else []
        finally:
            self._auth_lock.release()

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到 JSON 文件 voi file locking."""
        self._auth_lock.acquire()
        try:
            self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write
            tmp_path = self.auth_keys_path.with_suffix('.tmp')
            tmp_path.write_text(
                json.dumps({"items": auth_keys}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp_path, self.auth_keys_path)
        finally:
            self._auth_lock.release()

    def load_accounts(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载账号数据"""
        return self._load_json_list(self.file_path)

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到 JSON 文件"""
        self._save_json_list(self.file_path, accounts)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载鉴权密钥数据"""
        if not self.auth_keys_path.exists():
            return []
        try:
            data = json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []
        if isinstance(data, dict):
            data = data.get("items")
        return data if isinstance(data, list) else []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到 JSON 文件"""
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.write_text(
            json.dumps({"items": auth_keys}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            # 检查文件是否可读写
            if self.file_path.exists():
                self.file_path.read_text(encoding="utf-8")
            return {
                "status": "healthy",
                "backend": "json",
                "file_exists": self.file_path.exists(),
                "file_path": str(self.file_path),
                "auth_keys_file_exists": self.auth_keys_path.exists(),
                "auth_keys_file_path": str(self.auth_keys_path),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "json",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        return {
            "type": "json",
            "description": "本地 JSON 文件存储",
            "file_path": str(self.file_path),
            "file_exists": self.file_path.exists(),
            "auth_keys_file_path": str(self.auth_keys_path),
            "auth_keys_file_exists": self.auth_keys_path.exists(),
        }
