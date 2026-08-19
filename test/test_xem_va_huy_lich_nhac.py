"""Người dùng phải XEM được và HUỶ được lịch nhắc của chính mình.

Sự cố thật 10/08/2026 (đoạn chat trên máy chủ, 07:53–07:56). Một việc theo lịch
bắn ra lúc 07:45 xin số liệu nhân sự. Người dùng muốn dừng nó, và không làm được
việc gì trong bốn lượt liền:

    07:53  "Hủy lịch nhắc báo cáo"        → bot xin mã lịch
    07:54  "Xem có những lịch nào"        → "em chưa có danh sách … anh vào
                                            phần Lịch nhắc trên ứng dụng"
    07:55  "Hiện nay tôi có lịch nào"     → trả về LỊCH ÂM Bính Ngọ, kèm dấu
                                            trích dẫn nội bộ của ChatGPT
    07:55  "Hiện nay tôi có lịch hẹn nào" → "Dạ em đã nhận phần dữ liệu tìm
                                            kiếm rồi ạ. Anh gửi giúp em câu hỏi
                                            cụ thể cần trả lời nhé"

Ba nguyên nhân rời nhau, cộng lại thành vòng khoá:

1. Chữ "hiện nay" khớp SEARCH_INTENT_PATTERNS ⇒ gateway đem cả câu đi tra
   Internet rồi nhét kết quả vào TRƯỚC câu hỏi thật, kèm mệnh lệnh "BẮT BUỘC ĐỌC
   VÀ TRẢ LỜI DỰA TRÊN ĐÂY". Lượt đó không còn gọi tool `schedule` nữa — hai câu
   trả lời cuối là bot đang trả lời chính khối tiêm vào.
2. Nhánh huỷ chỉ nhận MÃ (hoặc 'all'). Mà mã chỉ hiện một lần lúc đặt lịch, tin
   nhắn khi lịch bắn không mang mã, và đường xem danh sách thì đang hỏng vì (1).
3. Bảng chỉ đường trong system prompt chỉ nêu ví dụ ĐẶT lịch, không có chữ nào
   về xem/huỷ — nên câu "Xem có những lịch nào" (không khớp mẫu tìm kiếm nào) bị
   model trả lời bằng tưởng tượng.

Module `services/protocol/openai_v1_chat_complete.py` cần Python ≥3.13 để import
(pyproject: requires-python), nên phần (1) được kiểm bằng cách BÓC thân hàm ra
chạy với stub — vẫn là kiểm hành vi, không phải chỉ so chữ.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities as caps  # noqa: E402
from services.agent import reminders as rem  # noqa: E402
from services.config import config  # noqa: E402

_GATEWAY = GOC / "services/protocol/openai_v1_chat_complete.py"


def _boc_ham(src: str, ten: str) -> str:
    """Lấy nguyên văn một hàm top-level trong file nguồn."""
    dau = src.index(f"\ndef {ten}(")
    sau = src.index("\ndef ", dau + 1)
    return src[dau:sau]


class TimTheoTenTests(unittest.TestCase):
    """`tim_theo_ten` — khớp lịch theo cái TÊN người dùng vừa gọi."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        rem._reset_for_tests(Path(self._tmp.name) / "reminders.sqlite")
        self._cfg = mock.patch.dict(
            config.data, {"agent_reminders": {"enabled": True, "tick_seconds": 5}},
        )
        self._cfg.start()
        # Nội dung ĐÚNG như mục đã bắn 07:45 trên máy chủ.
        self.uid = "zalop_zgr-abc:u77"
        self._dat("Hỏi anh lấy thông tin nhân sự trong ngày để lập báo cáo theo mẫu")
        self._dat("Nhắc anh uống thuốc huyết áp")

    def tearDown(self) -> None:
        self._cfg.stop()
        rem._reset_for_tests()
        self._tmp.cleanup()

    def _dat(self, text: str, uid: str | None = None) -> dict:
        return rem.create(uid or self.uid, text,
                          {"kind": "once", "due_at": time.time() + 600,
                           "next_run_at": time.time() + 600}, mode="task")

    def test_khop_bang_ten_nguoi_dung_goi(self) -> None:
        """Đúng câu đã thất bại: "Hủy lịch báo cáo nhân sự"."""
        khop = rem.tim_theo_ten(self.uid, "lịch báo cáo nhân sự")
        self.assertEqual(len(khop), 1, "không khớp được mục báo cáo nhân sự")
        self.assertIn("nhân sự", khop[0]["text"])

    def test_khong_can_dau(self) -> None:
        self.assertEqual(len(rem.tim_theo_ten(self.uid, "bao cao nhan su")), 1)

    def test_khong_can_dung_thu_tu_tu(self) -> None:
        self.assertEqual(len(rem.tim_theo_ten(self.uid, "nhân sự báo cáo")), 1)

    def test_doi_DU_moi_tu_chu_khong_phai_mot_tu(self) -> None:
        """"báo cáo nhân sự" không được quét luôn mục khác có chữ "nhắc"."""
        khop = rem.tim_theo_ten(self.uid, "báo cáo nhân sự")
        self.assertEqual([r["text"] for r in khop],
                         ["Hỏi anh lấy thông tin nhân sự trong ngày "
                          "để lập báo cáo theo mẫu"])

    def test_chi_toan_tu_goi_lich_thi_KHONG_doan(self) -> None:
        """"huỷ lịch nhắc" không nêu mục nào → trả rỗng để nơi gọi đi hỏi lại."""
        for cau in ("lịch nhắc", "cái lịch", "việc", "nhắc"):
            self.assertEqual(rem.tim_theo_ten(self.uid, cau), [],
                             f"{cau!r} không đủ thông tin mà vẫn khớp mục nào đó")

    def test_khong_thay_thi_rong(self) -> None:
        self.assertEqual(rem.tim_theo_ten(self.uid, "họp giao ban"), [])

    def test_khong_vuot_sang_nguoi_khac(self) -> None:
        self._dat("báo cáo nhân sự của người khác", uid="zalop_zgr-abc:u99")
        khop = rem.tim_theo_ten(self.uid, "báo cáo nhân sự")
        self.assertEqual(len(khop), 1)
        self.assertNotIn("người khác", khop[0]["text"])

    def test_mucdisabled_khong_hien(self) -> None:
        r = self._dat("nhắc gọi khách hàng Minh")
        rem.cancel(self.uid, r["id"])
        self.assertEqual(rem.tim_theo_ten(self.uid, "gọi khách hàng Minh"), [])


class HuyLichQuaToolTests(unittest.TestCase):
    """Nhánh `schedule(op=cancel)` — huỷ được mà không cần mã."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        rem._reset_for_tests(Path(self._tmp.name) / "reminders.sqlite")
        self._cfg = mock.patch.dict(
            config.data, {"agent_reminders": {"enabled": True, "tick_seconds": 5}},
        )
        self._cfg.start()
        self.uid = "zalop_zgr-abc:u77"
        self.ctx = {"user_id": self.uid}

    def tearDown(self) -> None:
        self._cfg.stop()
        rem._reset_for_tests()
        self._tmp.cleanup()

    def _dat(self, text: str) -> dict:
        return rem.create(self.uid, text,
                          {"kind": "once", "due_at": time.time() + 600,
                           "next_run_at": time.time() + 600}, mode="task")

    def _huy(self, **args) -> str:
        return str(caps._h_schedule({"op": "cancel", **args}, self.ctx).get("text") or "")

    def test_huy_bang_TEN_khong_can_ma(self) -> None:
        self._dat("Hỏi anh lấy thông tin nhân sự trong ngày để lập báo cáo theo mẫu")
        out = self._huy(text="báo cáo nhân sự")
        self.assertIn("huỷ rồi", out.lower(), out)
        self.assertEqual(rem.list_for(self.uid), [], "mục vẫn còn sau khi báo đã huỷ")

    def test_ten_di_qua_field_id_van_huy_duoc(self) -> None:
        """Model hay nhét tên vào `id`. Không phải mã thì coi là tên, đừng bỏ cuộc."""
        self._dat("Hỏi anh lấy thông tin nhân sự để lập báo cáo theo mẫu")
        out = self._huy(id="báo cáo nhân sự")
        self.assertIn("huỷ rồi", out.lower(), out)
        self.assertEqual(rem.list_for(self.uid), [])

    def test_ma_dung_van_huy_nhu_cu(self) -> None:
        r = self._dat("nhắc uống thuốc")
        out = self._huy(id=r["id"])
        self.assertIn(r["id"], out)
        self.assertEqual(rem.list_for(self.uid), [])

    def test_nhieu_muc_khop_thi_HOI_chu_khong_tu_chon(self) -> None:
        a = self._dat("báo cáo nhân sự ca sáng")
        b = self._dat("báo cáo nhân sự ca chiều")
        out = self._huy(text="báo cáo nhân sự")
        self.assertIn(a["id"], out)
        self.assertIn(b["id"], out)
        self.assertEqual(len(rem.list_for(self.uid)), 2,
                         "huỷ nhầm/huỷ bừa khi có nhiều mục khớp")

    def test_khong_khop_thi_DUA_DANH_SACH_chu_khong_xin_ma(self) -> None:
        r = self._dat("nhắc họp giao ban thứ hai")
        out = self._huy(text="báo cáo nhân sự")
        self.assertIn(r["id"], out, "không khớp thì phải cho họ thấy đang có gì")
        self.assertIn("giao ban", out)
        self.assertEqual(len(rem.list_for(self.uid)), 1)

    def test_khong_co_gi_thi_noi_khong_co_gi(self) -> None:
        out = self._huy(text="báo cáo nhân sự")
        self.assertIn("không có", out.lower())

    def test_huy_tat_ca_van_chay(self) -> None:
        self._dat("việc 1")
        self._dat("việc 2")
        out = self._huy(id="all")
        self.assertIn("2", out)
        self.assertEqual(rem.list_for(self.uid), [])

    def test_op_list_liet_ke_kem_ma(self) -> None:
        r = self._dat("báo cáo nhân sự hằng ngày")
        out = str(caps._h_schedule({"op": "list"}, self.ctx).get("text") or "")
        self.assertIn(r["id"], out)
        self.assertIn("báo cáo nhân sự", out)


class KhongTuTiemSearchVaoLuotAgentTests(unittest.TestCase):
    """Lượt agentic mang tool riêng thì gateway KHÔNG tự tiêm kết quả search.

    Bóc thân `_should_inject_search` ra chạy với stub, vì module gốc cần
    Python ≥3.13 (pyproject) trong khi test có thể chạy trên bản thấp hơn.

    Từ 19/08 có NGOẠI LỆ: model web-reverse không bao giờ phát tool_calls, nên
    nhường quyền cho nó là không ai tra cứu — lượt của model đó vẫn được tiêm.
    Stub `_model_bo_qua_tools` bên dưới thay cho hàm thật trong module gốc.
    """

    @classmethod
    def setUpClass(cls) -> None:
        src = _GATEWAY.read_text(encoding="utf-8")
        ns: dict = {
            "search_service": type("S", (), {"is_enabled": True})(),
            "_thread_denies": lambda body, group: False,
            "_is_trivial_chat": lambda t: False,
            "_is_smarthome_query": lambda t: False,
            "_model_bo_qua_tools": lambda model: "chatgpt" in str(model or ""),
            "dict": dict,
        }
        exec(_boc_ham(src, "_should_inject_search"), ns)
        cls.f = staticmethod(ns["_should_inject_search"])

    def _goi(self, body: dict, text: str = "Hiện nay tôi có lịch hẹn nào") -> bool:
        return type(self).f(body, False, False, False, text)

    def test_luot_agent_co_tool_thi_KHONG_tiem(self) -> None:
        self.assertFalse(self._goi({"x_agent_internal": True,
                                    "tools": [{"function": {"name": "schedule"}}]}),
                         "vẫn tiêm search vào lượt agent → cướp lượt gọi tool")

    def test_model_web_reverse_thi_VAN_tiem(self) -> None:
        """Model không gọi được tool: tiêm search là đường tra cứu duy nhất."""
        self.assertTrue(self._goi({"x_agent_internal": True,
                                   "model": "chatgpt_free",
                                   "tools": [{"function": {"name": "web_search"}}]}),
                        "model web-reverse mà không tiêm → bot không bao giờ tra web")

    def test_client_thuong_VAN_tiem_nhu_cu(self) -> None:
        self.assertTrue(self._goi({}), "chặn quá rộng, client thường mất tra web")

    def test_loi_goi_phu_cua_capability_van_tiem(self) -> None:
        """Lời gọi nội bộ KHÔNG kèm tool (tóm tắt, dịch…) giữ hành vi cũ."""
        self.assertTrue(self._goi({"x_agent_internal": True}))

    def test_client_ngoai_tu_gan_co_ma_khong_co_tool_thi_van_tiem(self) -> None:
        self.assertTrue(self._goi({"tools": [{"function": {"name": "x"}}]}))


class DauTrichDanKhongRoRaNguoiDungTests(unittest.TestCase):
    """Dấu trích dẫn ChatGPT bọc ký tự Unicode vùng riêng cũng phải bị xoá."""

    @classmethod
    def setUpClass(cls) -> None:
        src = _GATEWAY.read_text(encoding="utf-8")
        ns: dict = {"re": re}
        for ln in src.split("\n"):
            if ln.startswith("_PUA = ") or ln.startswith("_CITE_TURN = "):
                exec(ln, ns)
        cls.cite = ns["_CITE_TURN"]

    def test_dang_tran(self) -> None:
        self.assertEqual(
            type(self).cite.sub("", "Lập thu citeturn0search0turn0search6"),
            "Lập thu ")

    def test_dang_boc_ky_tu_vung_rieng(self) -> None:
        """Chính chuỗi đã rò ra người dùng 07:55 ngày 10/08."""
        s, sep, e = chr(0xE200), chr(0xE202), chr(0xE201)
        goc = f"Tiết khí: Lập thu {s}cite{sep}turn0search0turn0search6{e}"
        con = type(self).cite.sub("", goc)
        self.assertNotIn("cite", con)
        self.assertNotIn("turn0", con)
        self.assertIn("Lập thu", con)

    def test_khong_an_chu_thuong_co_cite(self) -> None:
        for giu in ("website citeseer nhé", "cite nguồn giúp em", "recite lại"):
            self.assertEqual(type(self).cite.sub("", giu), giu)


class BangChiDuongTests(unittest.TestCase):
    """System prompt phải dạy đường XEM và HUỶ, không chỉ đường ĐẶT."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = (GOC / "services/agent/orchestrator.py").read_text(encoding="utf-8")
        i = cls.src.index("## Bảng chỉ đường")
        cls.bang = cls.src[i:i + 4000]

    def test_co_duong_xem_danh_sach(self) -> None:
        self.assertIn("schedule(op=list)", self.bang)

    def test_co_duong_huy(self) -> None:
        self.assertIn("op=cancel", self.bang)

    def test_noi_ro_khong_tra_web_chu_lich(self) -> None:
        self.assertIn("KHÔNG tra web", self.bang)

    def test_cam_bao_nguoi_dung_tu_mo_ung_dung(self) -> None:
        self.assertIn("mở ứng dụng", self.bang)


class KhongConVetGoLoiGhiTmpTests(unittest.TestCase):
    """Không đổ nguyên request/response ra /tmp mỗi lượt.

    `/tmp` dùng chung cho mọi tiến trình trong container, mà body mang cả system
    prompt lẫn nội dung người dùng vừa gõ. Đây là vết gỡ lỗi, không phải tính
    năng — và nó chạy ở MỌI request, không có công tắc nào tắt được.
    """

    # Soi LỆNH mở file, không soi chữ: chú thích "đã gỡ đoạn ghi /tmp/…" là
    # phần cần giữ (nó ghi lại vì sao gỡ), nên tìm theo tên đường dẫn sẽ bắt
    # nhầm chính chú thích đó.
    def test_gateway_khong_ghi_tmp(self) -> None:
        self.assertNotIn('open("/tmp/', _GATEWAY.read_text(encoding="utf-8"))

    def test_gateway_khong_log_nguyen_cau_tra_loi(self) -> None:
        src = _GATEWAY.read_text(encoding="utf-8")
        self.assertNotIn('"event": "debug_final_result"', src)

    def test_provider_codex_khong_ghi_tmp(self) -> None:
        src = (GOC / "services/providers/openai_oauth.py").read_text(encoding="utf-8")
        self.assertNotIn('open("/tmp/', src)
        self.assertNotIn("_log_event(", src)


class KhongCoKnobAoTests(unittest.TestCase):
    """Tài liệu không được khai một khoá cấu hình mà không code nào đọc."""

    def test_max_task_seconds_khong_con_duoc_khai(self) -> None:
        """Dạng liệt kê thụt lề `    <khoá>: <kiểu>` là chỗ khai knob.

        Nhắc tên nó trong câu giải thích thì được (và nên) — điều bị cấm là khai
        nó như một khoá cấu hình dùng được, vì không dòng code nào đọc.
        """
        src = (GOC / "services/agent/reminders.py").read_text(encoding="utf-8")
        self.assertNotIn("    max_task_seconds:", src,
                         "vẫn khai knob mà không nơi nào đọc")
        self.assertIn("    tick_seconds:", src, "khai sai chỗ hoặc mất knob thật")


if __name__ == "__main__":
    unittest.main()
