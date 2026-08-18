"""Nhãn `free` phải thắng plan, đúng nguyên tắc hàm tự đặt ra.

``account_group`` mở đầu bằng câu "Type tags beat plan", và đã áp đúng cho
``standard``/``openai``. Nhưng nhãn ``free`` thì chưa: tài khoản gắn
``type=free`` mà upstream báo ``plan=plus`` vẫn rơi xuống luật "gói trả phí →
pool Codex".

Đo 18/08 trên máy chủ thật: ``bios.disused99+…@icloud.com`` có ``type=free``,
``plan=plus`` và đang nằm trong pool **codex**, trong khi nó được thêm vào để
dùng như tài khoản free qua chatgpt.com. Xếp nhầm pool nghĩa là nó bị định
tuyến bằng đường Codex và bị bộ khôi phục Codex nhận nuôi.
"""

from __future__ import annotations

import pytest


@pytest.mark.pure
def test_nhan_free_kem_goi_plus_van_o_pool_free():
    """Đúng bản ghi đo được trên máy chủ."""
    from services.account_service import account_group

    acc = {
        "email": "bios.disused99+6e84t67f@icloud.com",
        "type": "free",
        "plan": "plus",
        "access_token": "eyJhbGciOiJIUzI1NiJ9.x.y",
        "source_type": "web",
    }
    assert account_group(acc) == "free"


@pytest.mark.pure
@pytest.mark.parametrize("goi", ["plus", "pro", "go", "business", "team", "enterprise"])
def test_moi_goi_tra_phi_deu_khong_keo_duoc_nhan_free(goi):
    from services.account_service import account_group

    assert account_group({"type": "free", "plan": goi}) == "free"


@pytest.mark.pure
def test_khong_co_nhan_thi_goi_tra_phi_van_ve_codex():
    """Chiều ngược lại: đừng vá xong lại kéo tài khoản Codex thật sang free."""
    from services.account_service import account_group

    assert account_group({"plan": "plus", "source_type": "web"}) == "codex"
    assert account_group({"plan": "go", "source_type": "web"}) == "codex"


@pytest.mark.pure
def test_nhan_codex_van_thang_nhu_cu():
    """Nhãn codex rõ ràng vẫn phải về pool codex."""
    from services.account_service import account_group

    assert account_group({"type": "codex", "plan": "free"}) == "codex"
    assert account_group({"type": "codex", "plan": "go"}) == "codex"


@pytest.mark.pure
def test_nhan_api_openai_van_thang_goi():
    """Trường hợp đã đúng từ trước — khoá lại kẻo vá chỗ này làm hỏng chỗ kia."""
    from services.account_service import account_group

    assert account_group({"type": "standard", "plan": "plus"}) == "openai"
    assert account_group({"access_token": "sk-abc", "plan": "pro"}) == "openai"
