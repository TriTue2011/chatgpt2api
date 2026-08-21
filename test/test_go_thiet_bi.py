"""Xoá thiết bị = GỠ TRÊN MÁY TRƯỚC, rồi mới xoá ở dự án.

Vì sao thứ tự này bắt buộc: xoá ở dự án trước thì token chết ngay và phiên bị
đóng — hết đường ra lệnh gỡ. Trên máy người dùng vẫn còn lịch tự chạy, nên agent
cứ bật lại mỗi lần mở máy và gõ cửa gateway bằng token đã chết, mãi mãi. Người
dùng "đã xoá thiết bị" nhưng phải tự đi tìm Task Scheduler mà tắt — không có gì
nói cho họ biết điều đó.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV_API = ROOT / "api" / "devices.py"
AGENT = ROOT / "deploy" / "device_agent" / "c2a_agent.py"
INSTALLER = ROOT / "deploy" / "device_agent" / "install-windows.ps1"


class TestThuTuXoa:
    def test_go_may_truoc_khi_xoa_config(self):
        s = DEV_API.read_text("utf-8")
        i = s.index("async def devices_remove")
        body = s[i:s.index("@router.post", i)]
        vt_go = body.index('session.call("uninstall"')
        vt_xoa = body.index("config.mutate(_apply)")
        assert vt_go < vt_xoa, "gỡ trên máy phải xảy ra TRƯỚC khi xoá ở dự án"

    def test_go_hong_van_xoa_o_du_an(self):
        """Token phải chết cho bằng được — đó là lớp bảo vệ thật. Gỡ hỏng chỉ là
        máy kia còn rác, không phải lý do giữ token sống."""
        s = DEV_API.read_text("utf-8")
        i = s.index("async def devices_remove")
        body = s[i:s.index("@router.post", i)]
        # nhánh except của lời gọi uninstall KHÔNG được return/raise
        j = body.index('session.call("uninstall"')
        khoi = body[j:body.index("config.mutate(_apply)")]
        assert "return" not in khoi and "raise" not in khoi

    def test_may_offline_thi_noi_ro(self):
        s = DEV_API.read_text("utf-8")
        i = s.index("async def devices_remove")
        body = s[i:s.index("@router.post", i)]
        assert "ghi_chu" in body and "-Uninstall" in body, \
            "offline mà im lặng thì người dùng tưởng đã sạch"

    def test_co_duong_bo_qua_khi_may_khong_con(self):
        """Máy đã bán/hỏng/cài lại Windows — phải xoá được mà không chờ gỡ."""
        s = DEV_API.read_text("utf-8")
        assert "uninstall: bool = Query(default=True)" in s

    def test_tra_ket_qua_go_cho_UI(self):
        s = DEV_API.read_text("utf-8")
        assert '"go_tren_may": go_may' in s


class TestOpUninstallOAgent:
    def test_agent_co_op_uninstall(self):
        s = AGENT.read_text("utf-8")
        assert '"uninstall": op_uninstall' in s

    def test_go_dung_ba_thu_tren_windows(self):
        s = AGENT.read_text("utf-8")
        i = s.index("def op_uninstall")
        body = s[i:s.index("\nOPS = {", i)]
        assert "schtasks" in body and "/Delete" in body, "không xoá lịch tự chạy"
        assert "C2A_TOKEN" in body, "không xoá token"
        assert "Remove-Item" in body, "không xoá thư mục cài"

    def test_xoa_thu_muc_sau_khi_tien_trinh_thoat(self):
        """Trên Windows không xoá được file .py đang mở — phải hẹn xoá sau."""
        s = AGENT.read_text("utf-8")
        i = s.index("def op_uninstall")
        body = s[i:s.index("\nOPS = {", i)]
        assert "Start-Sleep" in body and "Start-Process" in body

    def test_chi_xoa_thu_muc_cua_chinh_no(self):
        """Người dùng có thể để c2a_agent.py ở chỗ khác — không xoá bừa."""
        s = AGENT.read_text("utf-8")
        i = s.index("def op_uninstall")
        body = s[i:s.index("\nOPS = {", i)]
        assert 'd.name == "c2a-agent"' in body

    def test_khong_tu_ket_thuc_tien_trinh(self):
        """Phải trả kết quả về gateway trước; agent chết khi phiên bị đóng."""
        s = AGENT.read_text("utf-8")
        i = s.index("def op_uninstall")
        body = s[i:s.index("\nOPS = {", i)]
        assert "sys.exit" not in body and "os._exit" not in body

    def test_uninstall_ngoai_ALL_OPS(self):
        """Không được để mô hình gọi 'uninstall' qua /op hay qua lời chat."""
        s = DEV_API.read_text("utf-8")
        m = re.search(r"^_ALL_OPS = .+$", s, re.M)
        assert m and "_SELF_OPS" not in m.group(0)
        assert '_SELF_OPS = {"uninstall"}' in s


class TestInstallerASCII:
    def test_ps1_thuan_ascii(self):
        """PowerShell 5.1 đọc .ps1 không BOM theo ANSI: tiếng Việt UTF-8 vỡ
        thành ký tự rác và PHÁ CÚ PHÁP — đã xảy ra thật (dấu nháy trong chuỗi
        throw vỡ, toàn file không parse được trên máy người dùng)."""
        raw = INSTALLER.read_bytes()
        xau = [b for b in raw if b > 127]
        assert not xau, f"installer có {len(xau)} byte ngoài ASCII"

    def test_chay_an_bang_pythonw(self):
        s = INSTALLER.read_text("utf-8")
        assert "pythonw" in s, "không dùng pythonw thì vẫn hiện cửa sổ"
        assert "-Hidden" in s and "New-ScheduledTask" in s

    def test_token_khong_nam_trong_arguments_task(self):
        """Cột Command line của Task Manager ai cùng máy cũng đọc được."""
        s = INSTALLER.read_text("utf-8")
        i = s.index("$argLine =")
        assert "$Token" not in s[i:s.index("$action", i)]
        assert "SetEnvironmentVariable(\"C2A_TOKEN\"" in s

    def test_tu_hoi_khi_chet(self):
        s = INSTALLER.read_text("utf-8")
        assert "-RestartCount" in s and "-RestartInterval" in s

    def test_co_duong_go(self):
        s = INSTALLER.read_text("utf-8")
        assert "if ($Uninstall)" in s


class TestAgentSongDuocKhiAn:
    def test_co_log_file(self):
        s = AGENT.read_text("utf-8")
        assert '"--log-file"' in s

    def test_khong_no_khi_stdout_None(self):
        """Dưới pythonw, sys.stdout là None — print đầu tiên ném AttributeError
        và agent chết trước cả khi kết nối, không dấu vết."""
        s = AGENT.read_text("utf-8")
        assert "if sys.stdout is None:" in s and "os.devnull" in s
