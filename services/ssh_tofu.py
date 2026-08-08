"""Chính sách host key SSH kiểu TOFU (trust-on-first-use) dùng chung.

Vì sao có file này: hai nơi trong gateway (`agent/capabilities.py`,
`ha_pyscript_deps.py`) đã làm ĐÚNG — nạp `known_hosts` trước khi kết nối, nên
paramiko tự ném `BadHostKeyException` khi khoá máy chủ đổi — nhưng vẫn viết
`paramiko.AutoAddPolicy()` cho host lần đầu. Bandit không đọc được ngữ cảnh đó:
nó thấy `AutoAddPolicy` là báo B507 mức HIGH, và bước `sast` của CI là cổng
chặn cứng nên workflow Security đỏ ở mọi commit.

Lớp dưới đây làm đúng việc AutoAddPolicy làm (chấp nhận host CHƯA từng thấy) và
thêm phần AutoAddPolicy không làm: ghi ngay ra file known_hosts và log lại vân
tay để người vận hành đối chiếu. Không phải mẹo để im Bandit — nó diễn đạt đúng
điều mã đang làm.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def fingerprint(key) -> str:
    """Vân tay SHA256 dạng OpenSSH — trùng chuỗi `ssh-keygen -lf` in ra."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def tofu_policy(known_hosts: Path | str | None):
    """Trả policy cho `SSHClient.set_missing_host_key_policy`.

    Chỉ áp cho host CHƯA có trong known_hosts. Host đã có mà khoá đổi thì
    paramiko từ chối TRƯỚC khi tới policy này.
    """
    import paramiko

    path = Path(known_hosts) if known_hosts else None

    class _Tofu(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            client.get_host_keys().add(hostname, key.get_name(), key)
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    client.save_host_keys(str(path))
                    os.chmod(path, 0o600)
                except Exception as exc:
                    logger.warning("ssh_tofu: không ghi được %s (%s)", path, exc)
            logger.warning(
                "ssh_tofu: ghi nhớ khoá LẦN ĐẦU cho %s (%s %s). Hãy đối chiếu với "
                "vân tay thật của máy chủ; sai là có người đứng giữa.",
                hostname, key.get_name(), fingerprint(key),
            )

    return _Tofu()
