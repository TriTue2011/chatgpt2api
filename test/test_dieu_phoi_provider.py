"""Đóng đinh hợp đồng của cửa điều phối provider (`_dispatch_provider`).

Lý do có file này: web2api đang chuyển từ chuỗi if/elif sang sổ đăng ký adapter
(``services/adapter_registry.py``). Test này ghi lại, CHO TỪNG provider: handler nào
được gọi, với đối số nào, có chuyển ``tools`` / ``tool_choice`` hay không, và hai việc
làm kèm (nén RTK, đường nhanh Codex của ``cgf/auto``). Sửa cấu trúc mà bảng này đổi là
đổi hành vi.

Khác `test_backend_router.py` (provider nào nhận tiền tố nào) — file này kiểm đoạn sau:
provider đó rồi đi đâu.
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.protocol.openai_v1_chat_complete as occ  # noqa: E402
from services import adapter_registry  # noqa: E402
from services import request_context as rc  # noqa: E402
from services.backend_router import PROVIDER_PREFIXES  # noqa: E402

MSGS = [{"role": "user", "content": "xin chào"}]
TOOLS = [{"type": "function", "function": {"name": "t"}}]
TC = "auto"

# handler trong occ gọi qua tên mô-đun; handler import muộn gọi qua đường dẫn đầy đủ
_TRONG_OCC = (
    "_handle_opencode_chat", "_handle_openai_oauth_chat", "_handle_gemini_chat",
    "_handle_agnes_chat", "_handle_antigravity_chat", "_handle_nvidia_chat",
    "_handle_tokenrouter_chat", "_handle_custom_openai_chat", "_handle_openai_api_chat",
)
_IMPORT_MUON = (
    "services.providers.web_proxy.handle_gemini_web_chat",
    "services.providers.chatgpt_free.handle_free_chat",
    "api.claude.handle_claude_chat",
    "api.gemini_web.handle_gemini_web_api_chat",
    "api.grok_web.handle_grok_web_chat",
)


def _nhan(x, body):
    """Gọn hoá đối số để so sánh: nhận ra messages/tools/body theo danh tính."""
    if x is MSGS:
        return "MSGS"
    if x is TOOLS:
        return "TOOLS"
    if x is body:
        return "BODY"
    return x


def chay(provider: str, *, model: str = "mdl", stream=False, body_model=None,
         tools=TOOLS, rtk=False, rtk_khac=False, oauth_loi=False):
    """Gọi `_dispatch_provider` với mọi handler bị thay bằng bộ ghi. Trả về danh sách lời gọi."""
    body = {"stream": stream}
    if body_model is not None:
        body["model"] = body_model
    lan: list[tuple] = []

    def bo_ghi(ten, tra=None, loi=False):
        def f(*a, **k):
            lan.append((ten, tuple(_nhan(x, body) for x in a),
                        tuple(sorted((kk, _nhan(v, body)) for kk, v in k.items()))))
            if loi:
                raise RuntimeError("oauth hỏng")
            return tra if tra is not None else {"ok": ten}
        return f

    def rtk_ghi(msgs, nguong, file_upload_threshold=0):
        lan.append(("rtk", (nguong, file_upload_threshold), ()))
        return msgs

    def slim(t):
        lan.append(("slim", (_nhan(t, body),), ()))
        return t

    route = SimpleNamespace(provider=provider, model=model)
    cfg = SimpleNamespace(rtk_enabled=rtk, rtk_other_enabled=rtk_khac)
    with mock.patch.multiple(
        occ,
        **{t: bo_ghi(t, loi=(oauth_loi and t == "_handle_openai_oauth_chat")) for t in _TRONG_OCC},
        _slim_tools_for_free=slim,
        config=cfg,
    ):
        ctxs = [mock.patch(d, bo_ghi(d.rsplit(".", 1)[1])) for d in _IMPORT_MUON]
        ctxs.append(mock.patch("services.protocol.conversation._rtk_compress_messages", rtk_ghi))
        for c in ctxs:
            c.start()
        try:
            kq = occ._dispatch_provider(route, MSGS, tools, TC, body)
        finally:
            for c in ctxs:
                c.stop()
    return lan, kq


# Provider có tiền tố trong `PROVIDER_PREFIXES` nhưng CHƯA có adapter — đo 10/10/2026.
# Gọi tới chúng hiện rơi lặng lẽ về chatgpt_free (log `unknown_provider`). Danh sách này
# chỉ được CO LẠI: viết adapter cho provider nào thì xoá tên nó khỏi đây.
CHUA_CO_ADAPTER = {
    "chatgpt_web", "cursor", "gemini_cli", "github", "iflow", "kiro",
    "ninerouter", "opencode_go", "perplexity_web", "qwen", "supercode",
}


class SoAdapterTests(unittest.TestCase):
    def test_moi_provider_co_tien_to_deu_co_adapter_hoac_khai_la_chua_co(self) -> None:
        thieu = {v for v in PROVIDER_PREFIXES.values() if adapter_registry.tim(v) is None}
        self.assertEqual(
            thieu, CHUA_CO_ADAPTER,
            "Thêm tiền tố provider mới thì phải đăng ký adapter (adapter_registry.dang_ky); "
            "đã viết adapter cho provider cũ thì xoá nó khỏi CHUA_CO_ADAPTER.",
        )

    def test_provider_dong_custom_tra_ra_adapter_custom(self) -> None:
        self.assertIs(adapter_registry.tim("custom:lv"), adapter_registry.tim("custom"))
        self.assertIsNone(adapter_registry.tim("khong_ton_tai:x"))

    def test_chi_chatgpt_tai_tep(self) -> None:
        tai = {m for m in adapter_registry.danh_sach() if adapter_registry.tim(m).tai_tep}
        self.assertEqual(tai, {"chatgpt", "chatgpt_free"})


class GhiNguonTraLoiTests(unittest.TestCase):
    """Cửa điều phối ghi NGUỒN THẬT của câu trả lời, không trông chờ từng provider tự khai.

    Đo 10/10/2026 trên `runs.sqlite`: 1.206/1.276 lượt chat+vision (94,5%) không có
    `dest_provider` vì chỉ ba provider tự gọi `note_provider_account`.
    """

    def setUp(self) -> None:
        rc.reset_all()

    def tearDown(self) -> None:
        rc.reset_all()

    def test_moi_provider_co_adapter_deu_de_lai_nguon(self) -> None:
        for prov in ("opencode", "gemini_free", "claude", "agnes", "openai_oauth", "codex",
                     "chatgpt", "chatgpt_free", "custom:lv", "grok_web", "gemini_web_api"):
            with self.subTest(provider=prov):
                rc.reset_all()
                chay(prov, model="m1")
                d = rc.get_dest()
                self.assertEqual((d.get("provider"), d.get("model")), (prov, "m1"))
                self.assertNotIn("yeu_cau", d)

    def test_thay_the_lang_le_thi_ghi_ca_nguoi_duoc_goi_lan_nguoi_tra_loi(self) -> None:
        chay("flow", model="banana-2-lite")
        d = rc.get_dest()
        self.assertEqual(d["provider"], "chatgpt_free")   # nơi THẬT sự trả lời
        self.assertEqual(d["yeu_cau"], "flow")              # nơi đã được yêu cầu

    def test_combo_nhieu_buoc_de_lai_vet_tung_buoc(self) -> None:
        chay("flow", model="a")
        chay("claude", model="b")
        vet = [(r["provider"], r.get("yeu_cau", "")) for r in rc.get_dest_trail()]
        self.assertEqual(vet, [("chatgpt_free", "flow"), ("claude", "")])


class DieuPhoiProviderTests(unittest.TestCase):
    # ── nhánh KHÔNG nhận tools: handler chỉ thấy (model, messages, stream, body) ──
    def test_nhanh_khong_nhan_tools(self) -> None:
        mong = {
            "opencode": ("_handle_opencode_chat", ("mdl", "MSGS", False, "BODY")),
            "gemini_free": ("_handle_gemini_chat", ("mdl", "MSGS", False, "BODY")),
            "gemini_web": ("handle_gemini_web_chat", ("mdl", "MSGS", False, "BODY")),
            "claude": ("handle_claude_chat", ("mdl", "MSGS", False, "BODY")),
            "grok_web": ("handle_grok_web_chat", ("mdl", "MSGS", False, "BODY")),
        }
        for prov, (ten, args) in mong.items():
            with self.subTest(provider=prov):
                lan, _ = chay(prov)
                self.assertEqual(lan, [(ten, args, ())])

    def test_gemini_web_api_nhan_them_base_url(self) -> None:
        lan, _ = chay("gemini_web_api")
        self.assertEqual(lan, [("handle_gemini_web_api_chat",
                                ("mdl", "MSGS", False, "BODY"), (("base_url", ""),))])

    # ── nhánh nhận tools + tool_choice ──
    def test_nhanh_nhan_tools(self) -> None:
        voi_tools = {
            "openai_oauth": "_handle_openai_oauth_chat",
            "codex": "_handle_openai_oauth_chat",
            "agnes": "_handle_agnes_chat",
            "antigravity": "_handle_antigravity_chat",
            "nvidia_nim": "_handle_nvidia_chat",
            "tokenrouter": "_handle_tokenrouter_chat",
            "openai_api": "_handle_openai_api_chat",
        }
        for prov, ten in voi_tools.items():
            with self.subTest(provider=prov):
                lan, _ = chay(prov, stream=True)
                self.assertEqual(lan, [(ten, ("mdl", "MSGS", "TOOLS", TC, True, "BODY"), ())])

    def test_custom_nhan_ca_ten_provider(self) -> None:
        lan, _ = chay("custom:lv")
        self.assertEqual(lan, [("_handle_custom_openai_chat",
                                ("custom:lv", "mdl", "MSGS", "TOOLS", TC, False, "BODY"), ())])

    # ── chatgpt / chatgpt_free ──
    def test_chatgpt_free_di_qua_slim_roi_handler_free(self) -> None:
        for prov in ("chatgpt_free", "chatgpt"):
            with self.subTest(provider=prov):
                lan, _ = chay(prov)
                self.assertEqual(lan, [
                    ("rtk", (100_000, 80_000), ()),
                    ("slim", ("TOOLS",), ()),
                    ("handle_free_chat", ("mdl", "MSGS", "TOOLS", TC, False, "BODY", mock.ANY), ()),
                ])

    def test_rtk_chatgpt_nguong_100k_va_tai_len_80k(self) -> None:
        for prov in ("chatgpt_free", "chatgpt"):
            with self.subTest(provider=prov):
                lan, _ = chay(prov, rtk=False)   # tải-tệp luôn chạy dù rtk tắt
                self.assertEqual(lan[0], ("rtk", (100_000, 80_000), ()))
                lan, _ = chay(prov, rtk=True)
                self.assertEqual(lan[0], ("rtk", (100_000, 80_000), ()))

    def test_rtk_provider_khac_chi_chay_khi_bat_rtk_other(self) -> None:
        lan, _ = chay("claude", rtk_khac=False)
        self.assertNotIn("rtk", [x[0] for x in lan])
        lan, _ = chay("claude", rtk_khac=True)
        self.assertEqual(lan[0], ("rtk", (100_000, 0), ()))

    def test_rtk_chatgpt_tat_va_khong_tai_len_thi_khong_chay(self) -> None:
        # provider khác + rtk_other tắt → không nén; chatgpt luôn có tải-tệp nên luôn chạy
        lan, _ = chay("opencode", rtk=True, rtk_khac=False)
        self.assertNotIn("rtk", [x[0] for x in lan])

    # ── cgf/auto: thử Codex trước, hỏng thì về free nguyên vẹn ──
    def test_cgf_auto_di_codex_truoc(self) -> None:
        for bm in ("cgf/auto", "free/auto", " CGF/Auto "):
            with self.subTest(body_model=bm):
                lan, kq = chay("chatgpt_free", body_model=bm)
                self.assertEqual(lan, [("rtk", (100_000, 80_000), ()),
                                       ("_handle_openai_oauth_chat",
                                        ("auto", "MSGS", "TOOLS", TC, False, "BODY"), ())])
                self.assertEqual(kq, {"ok": "_handle_openai_oauth_chat"})

    def test_cgf_auto_codex_hong_thi_ve_free(self) -> None:
        lan, _ = chay("chatgpt_free", body_model="cgf/auto", oauth_loi=True)
        self.assertEqual([x[0] for x in lan],
                         ["rtk", "_handle_openai_oauth_chat", "slim", "handle_free_chat"])

    def test_cgf_auto_khong_ap_cho_provider_chatgpt_tran(self) -> None:
        # `chatgpt` (không free) với body_model cgf/auto: đi nhánh free chung, vẫn thử Codex
        lan, _ = chay("chatgpt", body_model="cgf/auto")
        self.assertEqual([x[0] for x in lan], ["rtk", "_handle_openai_oauth_chat"])

    def test_chatgpt_free_model_khac_khong_thu_codex(self) -> None:
        lan, _ = chay("chatgpt_free", body_model="cgf/gpt-5")
        self.assertNotIn("_handle_openai_oauth_chat", [x[0] for x in lan])

    # ── provider không có nhánh: hiện rơi về chatgpt_free (ghi cảnh báo) ──
    def test_provider_khong_co_nhanh_roi_ve_chatgpt_free(self) -> None:
        for prov in ("flow", "ninerouter", "supercode", "opencode_go", "qwen", "khong_ton_tai"):
            with self.subTest(provider=prov):
                with self.assertLogs("chatgpt2api", level="WARNING") as cm:
                    lan, _ = chay(prov)
                self.assertEqual([x[0] for x in lan if x[0] in ("slim", "handle_free_chat")],
                                 ["slim", "handle_free_chat"])
                self.assertTrue(any("unknown_provider" in m for m in cm.output), cm.output)

    # ── dấu `:`-marker bị bóc khỏi tên model trước khi giao cho handler ──
    def test_marker_bi_boc_khoi_model(self) -> None:
        lan, _ = chay("claude", model="opus:tts")
        self.assertEqual(lan[-1][1][0], "opus")


if __name__ == "__main__":
    unittest.main()
