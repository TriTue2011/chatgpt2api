from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Column, String, Text, create_engine, Integer, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from services.storage.base import StorageBackend

Base = declarative_base()


class AccountModel(Base):
    """账号数据模型"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # KHÔNG đặt trần độ dài. Cột này từng là varchar(2048) và token của nhà cung
    # cấp cứ dài dần theo thời gian: đo 24/08/2026 trên máy chủ thật, token dài
    # nhất đang lưu là 1.964 ký tự — sát trần — và mỗi lần làm mới token đều đổ
    # `StringDataRightTruncation`, sáu lần trong một giờ. Hỏng ở đây không chỉ
    # mất token: lượt chat nào đi qua provider đó cũng chết theo, rồi rơi xuống
    # model dự phòng yếu hơn.
    #
    # Ràng buộc unique vẫn giữ (bắt trùng token lúc lưu). Lưu ý cho người sau:
    # chỉ mục btree của Postgres chịu khoảng 2.704 byte một mục, nên nếu token
    # có ngày vượt mốc đó thì phải chuyển sang so trùng bằng băm.
    access_token = Column(Text, unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)  # JSON 格式存储完整账号数据


class AuthKeyModel(Base):
    """鉴权密钥数据模型"""
    __tablename__ = "auth_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(255), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)


class ConfigDocumentModel(Base):
    """Toàn bộ config.json ở dạng 1 document JSON — CHỦ Ý dùng cột Text/JSON
    thay vì tách cột kiểu (typed columns) cho từng field, để field lạ/mới
    thêm sau này KHÔNG BAO GIỜ bị rơi khi lưu vào DB (root cause sự cố production:
    đổi STORAGE_BACKEND=postgres làm mất 42 khoá config vì config.json từng
    nằm ngoài storage abstraction). Chỉ 1 hàng cố định (id=1)."""
    __tablename__ = "config_document"

    id = Column(Integer, primary_key=True, autoincrement=False)
    data = Column(Text, nullable=False)


class DatabaseStorageBackend(StorageBackend):
    """数据库存储后端（支持 SQLite、PostgreSQL、MySQL 等）"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,  # 自动检测连接是否有效
            pool_recycle=3600,   # 1小时回收连接
        )
        Base.metadata.create_all(self.engine)
        self._noi_cot_access_token()
        self.Session = sessionmaker(bind=self.engine)

    #: Cột nào từng khai có trần độ dài mà nay phải là text tự do.
    _COT_PHAI_NOI = (("accounts", "access_token"),)

    def _noi_cot_access_token(self) -> None:
        """Nới cột đã tạo từ trước từ varchar(n) sang text.

        `create_all` chỉ tạo bảng còn THIẾU, nó không sửa cột của bảng đã có.
        Nên đổi khai báo trong model là đủ cho máy mới, nhưng máy đang chạy vẫn
        giữ nguyên varchar(2048) và vẫn hỏng — đúng thứ đang xảy ra trên máy chủ
        ngày 24/08/2026.

        Chạy được nhiều lần: có trần thì mới nới, không có thì thôi. Hỏng thì ghi
        log rồi đi tiếp — không được để một lần ALTER thất bại làm chết cả tiến
        trình lúc khởi động.
        """
        # SQLite không áp trần độ dài của VARCHAR nên không có gì để nới. MySQL
        # thì không nới được kiểu này: cột TEXT của nó đòi khai độ dài khoá cho
        # chỉ mục unique. Máy chủ đang dùng Postgres, nên chỉ làm cho Postgres —
        # gặp DB khác thì để nguyên chứ không đoán.
        if self.engine.dialect.name != "postgresql":
            return
        try:
            from sqlalchemy import inspect as _inspect
            insp = _inspect(self.engine)
            bang_co_san = set(insp.get_table_names())
            for bang, cot in self._COT_PHAI_NOI:
                if bang not in bang_co_san:
                    continue
                info = next((c for c in insp.get_columns(bang) if c["name"] == cot), None)
                if info is None or not getattr(info["type"], "length", None):
                    continue
                with self.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {bang} ALTER COLUMN {cot} TYPE TEXT"))
                print(f"[storage] Đã nới cột {bang}.{cot} từ varchar"
                      f"({info['type'].length}) sang TEXT")
        except Exception as exc:
            print(f"[storage] Không nới được cột access_token: {exc}")

    def load_accounts(self) -> list[dict[str, Any]]:
        """从数据库加载账号数据"""
        session = self.Session()
        try:
            accounts = []
            for row in session.query(AccountModel).all():
                try:
                    account_data = json.loads(row.data)
                    if isinstance(account_data, dict):
                        accounts.append(account_data)
                except json.JSONDecodeError:
                    continue
            return accounts
        finally:
            session.close()

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到数据库"""
        self._save_rows(AccountModel, accounts, "access_token")

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从数据库加载鉴权密钥数据"""
        return self._load_rows(AuthKeyModel)

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到数据库"""
        self._save_rows(AuthKeyModel, auth_keys, "id", "key_id")

    _CONFIG_DOC_ID = 1

    def load_config(self) -> dict[str, Any]:
        """加载全局配置文档（单行 JSON document，xem ConfigDocumentModel）。"""
        session = self.Session()
        try:
            row = session.query(ConfigDocumentModel).filter_by(id=self._CONFIG_DOC_ID).first()
            if row is None:
                return {}
            try:
                data = json.loads(row.data)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        finally:
            session.close()

    def save_config(self, data: dict[str, Any]) -> None:
        """保存全局配置文档 — upsert 1 hàng duy nhất, ghi đè nguyên document
        (không tách cột) nên không key nào có thể bị rơi khi lưu."""
        session = self.Session()
        try:
            payload = json.dumps(data, ensure_ascii=False)
            row = session.query(ConfigDocumentModel).filter_by(id=self._CONFIG_DOC_ID).first()
            if row is None:
                session.add(ConfigDocumentModel(id=self._CONFIG_DOC_ID, data=payload))
            else:
                row.data = payload
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def _load_rows(self, model: type[AccountModel] | type[AuthKeyModel]) -> list[dict[str, Any]]:
        session = self.Session()
        try:
            items = []
            for row in session.query(model).all():
                try:
                    item_data = json.loads(row.data)
                    if isinstance(item_data, dict):
                        items.append(item_data)
                except json.JSONDecodeError:
                    continue
            return items
        finally:
            session.close()

    def _save_rows(
        self,
        model: type[AccountModel] | type[AuthKeyModel],
        items: list[dict[str, Any]],
        source_key: str,
        target_key: str | None = None,
    ) -> None:
        session = self.Session()
        try:
            session.query(model).delete()
            for item in items:
                if not isinstance(item, dict):
                    continue
                key_value = str(item.get(source_key) or "").strip()
                if not key_value:
                    continue
                session.add(
                    model(
                        **{target_key or source_key: key_value},
                        data=json.dumps(item, ensure_ascii=False),
                    )
                )
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            session = self.Session()
            try:
                # 尝试执行简单查询
                session.execute(text("SELECT 1"))
                count = session.query(AccountModel).count()
                auth_key_count = session.query(AuthKeyModel).count()
                has_config = session.query(ConfigDocumentModel).filter_by(id=self._CONFIG_DOC_ID).first() is not None
                return {
                    "status": "healthy",
                    "backend": "database",
                    "database_url": self._mask_password(self.database_url),
                    "account_count": count,
                    "auth_key_count": auth_key_count,
                    "has_config_document": has_config,
                }
            finally:
                session.close()
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "database",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        db_type = "unknown"
        if "sqlite" in self.database_url:
            db_type = "sqlite"
        elif "postgresql" in self.database_url or "postgres" in self.database_url:
            db_type = "postgresql"
        elif "mysql" in self.database_url:
            db_type = "mysql"
        
        return {
            "type": "database",
            "db_type": db_type,
            "description": f"数据库存储 ({db_type})",
            "database_url": self._mask_password(self.database_url),
        }

    @staticmethod
    def _mask_password(url: str) -> str:
        """隐藏数据库连接字符串中的密码"""
        if "://" not in url:
            return url
        try:
            protocol, rest = url.split("://", 1)
            if "@" in rest:
                credentials, host = rest.split("@", 1)
                if ":" in credentials:
                    username, _ = credentials.split(":", 1)
                    return f"{protocol}://{username}:****@{host}"
            return url
        except Exception:
            return url
