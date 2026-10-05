"""Hướng dẫn Điện nhà / MikroTik ở web và ở docs/ KHÔNG được lệch nhau (chủ máy 05/10/2026: "hướng dẫn mới phải đầy
đủ cho các phần. Readme nữa").

Web không đọc được docs/ (ảnh Docker chỉ chép web/), nên cùng nội dung nằm hai nơi. Test này đòi mỗi khối lệnh,
mỗi bước và mỗi tên file trong `huong-dan-dien-mang.tsx` có NGUYÊN VĂN trong `docs/DIEN_UPS_VA_MANG_NHA.md`."""
from __future__ import annotations

import re
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
TSX = (GOC / "web/src/app/settings/components/huong-dan-dien-mang.tsx").read_text(encoding="utf-8")
DOC = (GOC / "docs/DIEN_UPS_VA_MANG_NHA.md").read_text(encoding="utf-8")


def _khoi_lenh() -> list[str]:
    """Mọi template literal (giữa hai dấu backtick) — chính là các khối lệnh. Bỏ thoát `\\${` của JS."""
    return [m.replace("\\${", "${") for m in re.findall(r"`(.*?)`", TSX, flags=re.S)]


def test_co_du_khoi_lenh():
    khoi = _khoi_lenh()
    assert len(khoi) == 19, f"tìm thấy {len(khoi)} khối — regex hỏng?"
    for k in khoi:
        assert f"```\n{k}\n```" in DOC, f"khối lệnh lệch với docs:\n{k[:200]}"


def test_buoc_va_ten_file_co_trong_docs():
    buoc = re.findall(r'^\s+"(.+)",$', TSX, flags=re.M)
    tep = re.findall(r'tep: "([^"]+)"', TSX)
    assert len(buoc) >= 20 and len(tep) >= 10
    for b in buoc:
        assert f"- {b}" in DOC, f"bước lệch với docs: {b}"
    for t in tep:
        assert f"`{t}`" in DOC, f"thiếu file {t} trong docs"


def test_khong_con_lo_mat_khau():
    gia_tri = [v for x in (TSX, DOC) for v in re.findall(r'password\s*=\s*"?([^\s"]+)', x)]
    assert gia_tri, "không thấy dòng password nào — regex hỏng?"
    assert all(v.startswith("MAT_KHAU") for v in gia_tri), f"chỉ dùng chỗ trống MAT_KHAU_…: {gia_tri}"
