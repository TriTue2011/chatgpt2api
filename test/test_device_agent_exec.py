"""Quyền chạy lệnh / tắt máy của c2a-agent — tầng chặn CUỐI CÙNG.

Vì sao dồn test vào agent chứ không phải gateway: agent cố ý KHÔNG TIN gateway.
Gateway bị chiếm, config bị sửa, hay ai đó gọi thẳng WebSocket thì lớp duy nhất
còn lại là mấy cái `need_*()` trong file agent này. Rò ở đây là mất máy.

Bốn nhóm quyền, mặc định TẮT hết trừ đọc:
    (đọc)          ls/read/stat/find + tra cứu hệ thống
    --allow-write  ghi/xoá file trong allowlist
    --allow-exec   chạy lệnh tuỳ ý + tắt tiến trình
    --allow-power  khoá/ngủ/đăng xuất/tắt/khởi động lại
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_AGENT_SRC = _ROOT / "deploy" / "device_agent" / "c2a_agent.py"

pytestmark = pytest.mark.pure


def _load_agent():
    """Nạp agent từ file. Nó thuần stdlib nên không cần dựng gì thêm."""
    spec = importlib.util.spec_from_file_location("_c2a_agent_probe", _AGENT_SRC)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ag():
    return _load_agent()


@pytest.fixture()
def ro(ag, tmp_path: Path):
    """Thiết bị chỉ đọc — mặc định của mọi thiết bị mới."""
    return ag.Guard([str(tmp_path)], False)


@pytest.fixture()
def full(ag, tmp_path: Path):
    return ag.Guard([str(tmp_path)], True, allow_exec=True, allow_power=True)


class TestMacDinhTuChoi:
    """Thiết bị mới KHÔNG được chạy lệnh hay tắt máy, dù gateway có gửi xuống."""

    @pytest.mark.parametrize(("op", "args"), [
        ("exec", {"command": "echo hi"}),
        ("kill", {"name": "chrome"}),
        ("kill", {"pid": "1234"}),
        ("power", {"action": "lock"}),
        ("power", {"action": "shutdown"}),
        ("power", {"action": "restart"}),
    ])
    def test_chi_doc_thi_bi_chan(self, ag, ro, op, args):
        r = ag.handle(ro, op, args)
        assert r.get("ok") is False, f"{op} KHÔNG bị chặn: {r}"
        assert "allow-" in str(r.get("error")), r

    def test_allow_write_khong_mo_duong_chay_lenh(self, ag, tmp_path: Path):
        """Quyền ghi file KHÔNG được kéo theo quyền chạy lệnh.

        Hai thứ khác mức hẳn nhau: ghi file còn bị allowlist thư mục chặn, còn
        một lệnh shell thì ra ngoài allowlist thoải mái.
        """
        g = ag.Guard([str(tmp_path)], True)          # chỉ --allow-write
        assert ag.handle(g, "exec", {"command": "echo x"}).get("ok") is False
        assert ag.handle(g, "power", {"action": "lock"}).get("ok") is False

    def test_allow_exec_khong_mo_duong_tat_may(self, ag, tmp_path: Path):
        g = ag.Guard([str(tmp_path)], True, allow_exec=True)
        assert ag.handle(g, "exec", {"command": "echo x"}).get("ok") is True
        r = ag.handle(g, "power", {"action": "shutdown"})
        assert r.get("ok") is False and "allow-power" in str(r.get("error"))

    def test_allow_power_khong_mo_duong_chay_lenh(self, ag, tmp_path: Path):
        g = ag.Guard([str(tmp_path)], False, allow_power=True)
        assert ag.handle(g, "exec", {"command": "echo x"}).get("ok") is False


class TestExecAllowlist:
    """`--exec-allow` giới hạn theo TIỀN TỐ lệnh."""

    def test_chi_cho_lenh_khai_truoc(self, ag, tmp_path: Path):
        g = ag.Guard([str(tmp_path)], True, allow_exec=True,
                     exec_allow=["echo", "ls"])
        assert ag.handle(g, "exec", {"command": "echo ok"}).get("ok") is True
        r = ag.handle(g, "exec", {"command": "rm -rf /"})
        assert r.get("ok") is False and "exec-allow" in str(r.get("error"))

    def test_khong_phan_biet_hoa_thuong_va_bo_khoang_trang_dau(self, ag, tmp_path: Path):
        g = ag.Guard([str(tmp_path)], True, allow_exec=True, exec_allow=["ECHO"])
        assert ag.handle(g, "exec", {"command": "   echo hi"}).get("ok") is True

    def test_rong_la_khong_gioi_han(self, ag, tmp_path: Path):
        g = ag.Guard([str(tmp_path)], True, allow_exec=True, exec_allow=[])
        assert ag.handle(g, "exec", {"command": "echo bat-ky"}).get("ok") is True

    def test_kill_cung_chiu_exec_allow(self, ag, tmp_path: Path):
        """Tắt tiến trình cũng là can thiệp — không được rẻ hơn chạy lệnh."""
        g = ag.Guard([str(tmp_path)], True, allow_exec=True, exec_allow=["winget"])
        r = ag.handle(g, "kill", {"name": "chrome"})
        assert r.get("ok") is False and "exec-allow" in str(r.get("error"))


class TestTranVaDauVaoXau:
    def test_thieu_command(self, ag, full):
        r = ag.handle(full, "exec", {})
        assert r.get("ok") is False and "command" in str(r.get("error"))

    def test_timeout_bi_kep(self, ag, full):
        """timeout khổng lồ không được biến thành treo agent vĩnh viễn."""
        r = ag.handle(full, "exec", {"command": "echo x", "timeout": 10**9})
        assert r.get("ok") is True          # bị kẹp về EXEC_TIMEOUT_MAX rồi chạy
        assert ag.EXEC_TIMEOUT_MAX <= 600

    def test_timeout_qua_han_bao_loi_khong_nem(self, ag, full):
        r = ag.handle(full, "exec", {"command": "sleep 3", "timeout": 1})
        assert r.get("ok") is False
        assert "thời gian" in str(r.get("stderr")) or r.get("rc") == -1

    def test_kill_thieu_ca_pid_va_name(self, ag, full):
        r = ag.handle(full, "kill", {})
        assert r.get("ok") is False and "pid" in str(r.get("error"))

    def test_power_action_la(self, ag, full):
        r = ag.handle(full, "power", {"action": "format-o-c"})
        assert r.get("ok") is False and "action" in str(r.get("error"))
        # Phải liệt kê action hợp lệ để chỗ gọi tự sửa được.
        assert "shutdown" in str(r.get("error"))

    def test_power_action_rong(self, ag, full):
        assert ag.handle(full, "power", {}).get("ok") is False

    def test_op_la_bi_tu_choi(self, ag, full):
        r = ag.handle(full, "khong-ton-tai", {})
        assert r.get("ok") is False and "không hỗ trợ" in str(r.get("error"))


class TestTraCuuKhongCanQuyen:
    """Nhóm tra cứu chạy lệnh CỐ ĐỊNH, chỉ đọc ⇒ thiết bị chỉ-đọc vẫn dùng được.

    Nếu bắt nhóm này đòi `--allow-exec` thì muốn xem RAM cũng phải mở quyền chạy
    lệnh tuỳ ý — đánh đổi ngược, nên cố ý KHÔNG làm vậy.
    """

    def test_sysinfo(self, ag, ro):
        r = ag.handle(ro, "sysinfo", {})
        assert r.get("ok") is True
        for k in ("hostname", "system", "machine", "cpu_count", "python",
                  "agent_version"):
            assert r.get(k), f"thiếu {k}"
        # Phải báo đúng quyền đang có, để chỗ gọi biết vì sao lệnh bị chặn.
        assert r["allow_write"] is False
        assert r["allow_exec"] is False
        assert r["allow_power"] is False

    def test_resources(self, ag, ro):
        r = ag.handle(ro, "resources", {})
        assert r.get("ok") is True
        assert (r.get("cpu_count") or 0) >= 1
        assert isinstance(r.get("disks"), list) and r["disks"], "không đọc được ổ đĩa"
        d = r["disks"][0]
        assert d["total"] > 0 and 0 <= d["percent"] <= 100

    def test_processes_sap_theo_ram_giam_dan(self, ag, ro):
        r = ag.handle(ro, "processes", {"limit": 5})
        assert r.get("ok") is True
        rows = r.get("processes") or []
        assert rows, "không đọc được tiến trình nào"
        assert len(rows) <= 5
        mems = [x.get("mem_kb") or 0 for x in rows]
        assert mems == sorted(mems, reverse=True), mems
        assert all(x.get("pid") for x in rows)

    def test_processes_ton_trong_tran(self, ag, ro):
        r = ag.handle(ro, "processes", {"limit": 10**6})
        assert len(r.get("processes") or []) <= ag.MAX_PROCS

    def test_processes_loc_theo_ten(self, ag, ro):
        r = ag.handle(ro, "processes", {"name": "khong-co-tien-trinh-nao-ten-nay"})
        assert r.get("ok") is True and (r.get("processes") or []) == []

    def test_screen_khong_doan_bua(self, ag, ro):
        """Trường không đo được phải là None kèm ghi chú, KHÔNG bịa True/False."""
        r = ag.handle(ro, "screen", {})
        assert r.get("ok") is True
        for k in ("locked", "display_on"):
            assert r.get(k) in (True, False, None)
        if r.get("locked") is None or r.get("display_on") is None:
            assert str(r.get("note") or "").strip(), "bỏ trống mà không nói lý do"

    def test_services(self, ag, ro):
        r = ag.handle(ro, "services", {})
        assert r.get("ok") is True
        assert isinstance(r.get("output"), str)


class TestAllowlistFileKhongBiAnhHuong:
    """Mở quyền chạy lệnh KHÔNG được nới allowlist của đường FILE."""

    def test_doc_ngoai_allowlist_van_bi_chan(self, ag, full, tmp_path: Path):
        ngoai = tmp_path.parent / "ngoai-pham-vi.txt"
        ngoai.write_text("bí mật", encoding="utf-8")
        r = ag.handle(full, "read", {"path": str(ngoai)})
        assert r.get("ok") is False and "phạm vi" in str(r.get("error"))

    def test_ghi_ngoai_allowlist_van_bi_chan(self, ag, full, tmp_path: Path):
        r = ag.handle(full, "write", {"path": str(tmp_path.parent / "x.txt"),
                                      "content": "a"})
        assert r.get("ok") is False


class TestCoDongLenh:
    """Cờ CLI phải tồn tại và mặc định TẮT — sai chỗ này là mở quyền do sơ suất."""

    def test_co_ba_co_quyen(self, ag):
        import argparse
        ap = argparse.ArgumentParser()
        # Đọc lại từ main() thì phải chạy cả vòng kết nối; kiểm bằng nguồn cho gọn.
        src = _AGENT_SRC.read_text(encoding="utf-8")
        for flag in ("--allow-write", "--allow-exec", "--allow-power", "--exec-allow"):
            assert flag in src, f"thiếu cờ {flag}"
        assert isinstance(ap, argparse.ArgumentParser)

    def test_mac_dinh_tat_het(self, ag, tmp_path: Path):
        g = ag.Guard([str(tmp_path)], False)
        assert g.allow_write is False
        assert g.allow_exec is False
        assert g.allow_power is False
        assert g.exec_allow == []

    def test_khong_khai_path_thi_khong_mo_gi(self, ag):
        """Fail-closed: allowlist rỗng ⇒ mọi đường dẫn bị từ chối."""
        g = ag.Guard([], True, allow_exec=True)
        r = ag.handle(g, "read", {"path": "/etc/passwd"})
        assert r.get("ok") is False


class TestGatewayPhanNhomOp:
    """Gateway phải xếp op vào đúng nhóm quyền (đọc nguồn — api/ cần fastapi)."""

    _SRC = _ROOT / "api" / "devices.py"

    def test_op_moi_nam_dung_nhom(self):
        src = self._SRC.read_text(encoding="utf-8")
        assert '_EXEC_OPS = {"exec", "kill"}' in src
        assert '_POWER_OPS = {"power"}' in src
        for op in ("sysinfo", "resources", "processes", "services", "screen"):
            assert f'"{op}"' in src, f"{op} chưa khai trong _INFO_OPS"

    def test_gateway_kiem_ca_hai_quyen_moi(self):
        src = self._SRC.read_text(encoding="utf-8")
        assert "_EXEC_OPS and not session.can_exec" in src
        assert "_POWER_OPS and not session.can_power" in src

    def test_op_khong_thuoc_nhom_nao_bi_tu_choi(self):
        src = self._SRC.read_text(encoding="utf-8")
        assert "if op not in _ALL_OPS" in src, (
            "phải kiểm theo _ALL_OPS, nếu không op mới lọt qua mà không ai gác"
        )
