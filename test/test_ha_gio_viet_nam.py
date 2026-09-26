"""Yêu cầu từ HA mang giờ Việt Nam thật (đo 26/09/2026 22:54: model đổi "22 giờ 54" thành
"23 giờ 54 (UTC+8)" vì HA 2026.9 không còn đưa giờ vào lời dặn)."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api.ai import _chen_gio_vn  # noqa: E402


def test_gio_dat_truoc_tin_nguoi_dung_cuoi():
    now = datetime(2026, 9, 26, 22, 54, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    msgs = [{"role": "system", "content": "persona"}, {"role": "user", "content": "Mấy giờ rồi"},
            {"role": "assistant", "content": "22 giờ 54"}, {"role": "user", "content": "Không"}]
    ra = _chen_gio_vn(msgs, now)
    assert [m["role"] for m in ra] == ["system", "user", "assistant", "system", "user"]
    assert ra[0]["content"] == "persona", "tiền tố lời dặn không đổi — giữ bộ nhớ đệm"
    assert "22:54" in ra[3]["content"] and "Thứ Bảy" in ra[3]["content"] and "26/09/2026" in ra[3]["content"]


def test_khong_co_tin_nguoi_dung_thi_them_cuoi():
    ra = _chen_gio_vn([{"role": "system", "content": "x"}])
    assert ra[-1]["role"] == "system" and "UTC+7" in ra[-1]["content"]
