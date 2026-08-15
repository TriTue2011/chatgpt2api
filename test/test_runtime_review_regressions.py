"""Regression tests for failures found during the production code review.

These are deliberately small and isolated: they exercise the state or boundary
that failed in production without requiring a bot account, Cloudflare, or a
browser session.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from services import cloudflare_tunnel as tunnel
from services import dich_cho as dc
from services import video_dich as vd
from services.agent import chatlog
from test._fakes import FakeTranslate, install_translate


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clear_pending():
    dc._pending.clear()
    yield
    dc._pending.clear()


@pytest.mark.pure
def test_get_pending_discards_an_expired_menu_before_returning_it():
    dc._pending["expired"] = {"ts": time.time() - dc._TTL - 1}

    assert dc.get_pending("expired") is None
    assert "expired" not in dc._pending


@pytest.mark.pure
def test_pop_pending_discards_an_expired_menu_before_consuming_it():
    dc._pending["expired"] = {"ts": time.time() - dc._TTL - 1}

    assert dc.pop_pending("expired") is None
    assert "expired" not in dc._pending


@pytest.mark.pure
def test_cloudflare_monitor_restarts_a_crashed_process(monkeypatch):
    class StopMonitor(Exception):
        pass

    monkeypatch.setattr(tunnel, "_tunnel_process", SimpleNamespace(
        poll=lambda: 23, returncode=23,
    ))
    monkeypatch.setattr(tunnel, "_token", lambda: "test-token")
    monkeypatch.setattr(tunnel, "_co_tien_trinh_he_thong", lambda: False)
    restarted: list[bool] = []
    monkeypatch.setattr(tunnel, "start_tunnel", lambda: restarted.append(True) or True)

    sleeps = 0

    def stop_after_one_cycle(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise StopMonitor

    monkeypatch.setattr(tunnel.time, "sleep", stop_after_one_cycle)

    with pytest.raises(StopMonitor):
        tunnel._monitor_loop()

    assert restarted == [True]


@pytest.mark.pure
def test_cloudflare_start_does_not_duplicate_a_system_process(monkeypatch):
    monkeypatch.setattr(tunnel, "_tunnel_process", None)
    monkeypatch.setattr(tunnel, "_token", lambda: "test-token")
    monkeypatch.setattr(tunnel, "_co_tien_trinh_he_thong", lambda: True)
    monkeypatch.setattr(
        tunnel.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )

    assert tunnel.start_tunnel() is True


@pytest.mark.pure
def test_cloudflare_restart_takes_ownership_back_from_an_orphan(monkeypatch):
    """Đổi token / bấm Restart phải giết được cloudflared của lần chạy trước.

    Đường tự động thì nhường tiến trình cũ (khỏi đẻ tunnel trùng), nhưng nếu
    đường restart cũng nhường thì token mới không bao giờ được áp dụng.
    """
    monkeypatch.setattr(tunnel, "_tunnel_process", None)
    monkeypatch.setattr(tunnel, "_token", lambda: "token-moi")
    con_song = [True]
    monkeypatch.setattr(tunnel, "_co_tien_trinh_he_thong", lambda: con_song[0])

    def giet() -> bool:
        con_song[0] = False
        return True

    monkeypatch.setattr(tunnel, "_giet_tien_trinh_he_thong", giet)
    da_chay: list[bool] = []
    monkeypatch.setattr(tunnel, "start_tunnel", lambda: da_chay.append(True) or True)

    assert tunnel.restart_tunnel() is True
    assert da_chay == [True]


@pytest.mark.pure
def test_cloudflare_restart_reports_failure_when_the_orphan_survives(monkeypatch):
    monkeypatch.setattr(tunnel, "_tunnel_process", None)
    monkeypatch.setattr(tunnel, "_token", lambda: "token-moi")
    monkeypatch.setattr(tunnel, "_co_tien_trinh_he_thong", lambda: True)
    monkeypatch.setattr(tunnel, "_giet_tien_trinh_he_thong", lambda: False)
    monkeypatch.setattr(
        tunnel, "start_tunnel",
        lambda: (_ for _ in ()).throw(AssertionError("must not start")),
    )

    assert tunnel.restart_tunnel() is False


@pytest.mark.pure
def test_chatlog_activity_returns_false_when_scope_resolution_fails():
    with mock.patch(
        "services.agent.scope.tach_khoa_phien",
        side_effect=RuntimeError("broken scope"),
    ):
        assert chatlog.ghi_hoat_dong("zalop_group:user", nhom="calendar", mo_ta="x") is False


@pytest.mark.pure
def test_explicit_video_source_is_passed_to_subtitle_selection(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://vn-translate:5000")
    seen: dict[str, str] = {}

    def fake_subtitles(url: str, dich_sang: str = "vi", nguon_biet: str = ""):
        seen.update(url=url, dich_sang=dich_sang, nguon_biet=nguon_biet)
        return [vd.Doan(0, 1, "konnichiwa")], "ja"

    monkeypatch.setattr(vd, "lay_phu_de", fake_subtitles)
    with install_translate(FakeTranslate(codes=("ja", "en"))):
        result = vd.dich_video("https://youtu.be/aircAruvnKk", "en", nguon_biet="ja")

    assert result["ok"] is True
    assert seen["nguon_biet"] == "ja"


@pytest.mark.pure
def test_zalo_personal_builds_pending_key_before_every_command_that_uses_it():
    source = (ROOT / "services" / "zalo_personal.py").read_text(encoding="utf-8")
    key_at = source.index('pkey = f"zalop:')
    assert key_at < source.index("_hd.mo(pkey)")
    assert key_at < source.index("_dc2.mo_stt(pkey)")
    assert key_at < source.index("_dc2.mo_tts(pkey")


@pytest.mark.pure
def test_thumbnail_route_uses_the_same_access_policy_as_images():
    media_source = (ROOT / "api" / "media.py").read_text(encoding="utf-8")
    system_source = (ROOT / "api" / "system.py").read_text(encoding="utf-8")

    assert "def require_image_access" in media_source
    assert "require_image_access(image_path, exp, sig)" in system_source


@pytest.mark.pure
def test_zalo_video_link_uses_the_source_language_the_user_picked():
    """Menu ba bước hỏi video nói tiếng gì — nhánh link phải dùng câu trả lời.

    Nhánh tệp đã truyền ``nguon_biet``; nhánh link thì không, nên người dùng
    chọn "Nhật" xong bot vẫn có thể lấy track tiếng Anh rồi dịch tiếp.
    """
    source = (ROOT / "services" / "zalo_personal.py").read_text(encoding="utf-8")
    goi = source.index('_vd.dich_video(pend["url"]')

    assert "nguon_biet=" in source[goi:goi + 300]


@pytest.mark.pure
def test_translation_page_uses_a_non_vietnamese_default_target_and_resolves_collisions():
    source = (ROOT / "web" / "src" / "app" / "dich" / "page.tsx").read_text(encoding="utf-8")

    assert 'const [target, setTarget] = useState("en")' in source
    assert "function doiNguon" in source
    assert "if (moi && moi === target)" in source


@pytest.mark.pure
def test_batch_codex_import_keeps_credentials_out_of_query_strings_and_marks_new_accounts_after_insert():
    source = (ROOT / "api" / "oauth.py").read_text(encoding="utf-8")
    batch = source[source.index("async def import_tokens_batch"):]

    assert "routerPassword: str | None = None" in source
    assert "query_params.get(\"password\")" not in batch
    assert batch.index("account_service.add_accounts_with_credentials") < batch.index(
        "account_service.update_account"
    )


@pytest.mark.pure
def test_teacher_student_delete_route_is_registered_exactly_once():
    tree = ast.parse((ROOT / "api" / "teacher.py").read_text(encoding="utf-8"))
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "delete"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                continue
            routes.append(decorator.args[0].value)

    assert routes.count("/api/teacher/students/{student_key}") == 1
