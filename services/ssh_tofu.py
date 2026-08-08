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

    Fail-closed: ghi known_hosts hỏng (hoặc không có nơi để ghi) → ném
    `paramiko.SSHException`, tức là TỪ CHỐI kết nối chứ không chấp nhận suông.
    """
    import paramiko

    path = Path(known_hosts) if known_hosts else None

    class _Tofu(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fp = fingerprint(key)
            # FAIL-CLOSED. Không ghi được khoá xuống đĩa thì mọi lần kết nối sau
            # đều là "lần đầu" — đúng cái lỗ của AutoAddPolicy mà file này sinh
            # ra để bịt. Chấp nhận host trong tình huống đó là im lặng tắt luôn
            # khả năng phát hiện khoá đổi, nên phải TỪ CHỐI kết nối.
            if path is None:
                raise paramiko.SSHException(
                    f"Từ chối kết nối tới {hostname}: chưa có nơi lưu known_hosts nên "
                    f"không thể phát hiện khoá máy chủ bị đổi ở lần sau. "
                    f"(vân tay lần này: {fp})"
                )
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                client.get_host_keys().add(hostname, key.get_name(), key)
                client.save_host_keys(str(path))
                os.chmod(path, 0o600)
            except Exception as exc:
                raise paramiko.SSHException(
                    f"Từ chối kết nối tới {hostname}: không lưu được khoá máy chủ vào "
                    f"{path} ({exc}). Không lưu được nghĩa là lần sau không phát hiện "
                    f"được khoá đổi. (vân tay lần này: {fp})"
                ) from exc
            logger.warning(
                "ssh_tofu: ghi nhớ khoá LẦN ĐẦU cho %s (%s %s). Hãy đối chiếu với "
                "vân tay thật của máy chủ; sai là có người đứng giữa.",
                hostname, key.get_name(), fp,
            )

    return _Tofu()
