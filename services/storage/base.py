from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """抽象存储后端基类"""

    @abstractmethod
    def load_accounts(self) -> list[dict[str, Any]]:
        """加载所有账号数据"""
        pass

    @abstractmethod
    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存所有账号数据"""
        pass

    @abstractmethod
    def load_auth_keys(self) -> list[dict[str, Any]]:
        """加载所有鉴权密钥数据"""
        pass

    @abstractmethod
    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存所有鉴权密钥数据"""
        pass

    @abstractmethod
    def load_config(self) -> dict[str, Any]:
        """加载全局配置文档（config.json 的存储无关等价物）。

        FIX: config.json trước đây nằm NGOÀI storage abstraction — ConfigStore
        luôn đọc/ghi thẳng file cục bộ bất kể STORAGE_BACKEND, nên đổi sang
        postgres/git thì config bị "biến mất" (đọc từ backend rỗng). Mọi
        backend phải implement để _load()/_save() của ConfigStore đi qua đây.
        """
        pass

    @abstractmethod
    def save_config(self, data: dict[str, Any]) -> None:
        """保存全局配置文档（xem load_config）。"""
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """健康检查，返回存储后端状态"""
        pass

    @abstractmethod
    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        pass
