from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _load():
    src = Path(__file__).parents[1] / "fw-tach-am" / "app.py"
    spec = importlib.util.spec_from_file_location("fw_tach_am_test", src)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _request(*, api_token: str = "bi-mat-thu", job_token: str = "job-123456789012"):
    headers = [(b"x-api-key", api_token.encode()),
               (b"x-job-token", job_token.encode())]
    return Request({"type": "http", "method": "POST", "path": "/unload",
                    "headers": headers, "query_string": b"",
                    "server": ("test", 80), "client": ("test", 1),
                    "scheme": "http"})


@pytest.mark.pure
def test_lenh_chi_xuat_instrumental_va_chia_nho_phim_dai(monkeypatch, tmp_path):
    app = _load()
    monkeypatch.setattr(app, "MODEL", "model-thu.ckpt")
    monkeypatch.setattr(app, "CHUNK_SECONDS", 300)

    cmd = app._lenh_tach("/tmp/vao.flac", str(tmp_path))

    assert cmd[0] == "audio-separator"
    assert cmd[cmd.index("--single_stem") + 1] == "Instrumental"
    assert cmd[cmd.index("--model_filename") + 1] == "model-thu.ckpt"
    assert cmd[cmd.index("--chunk_duration") + 1] == "300"
    assert cmd[cmd.index("--model_file_dir") + 1] == "/data/models"
    assert "--use_soundfile" in cmd


@pytest.mark.pure
def test_chon_dung_mot_track_nen_khong_nhan_nham_input(tmp_path):
    app = _load()
    (tmp_path / "input.flac").write_bytes(b"input")
    instrumental = tmp_path / "movie_(Instrumental)_model.wav"
    instrumental.write_bytes(b"RIFF" + b"0" * 200)

    assert app._tim_track_nen(str(tmp_path), str(tmp_path / "input.flac")) == str(instrumental)

    (tmp_path / "track-khac.wav").write_bytes(b"RIFF" + b"1" * 200)
    with pytest.raises(RuntimeError, match="đúng một track"):
        app._tim_track_nen(str(tmp_path), str(tmp_path / "input.flac"))


@pytest.mark.integration
def test_unload_dung_that_process_group_truoc_khi_nha_gpu():
    app = _load()
    app.API_TOKEN = "bi-mat-thu"
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    app._active_process = proc
    app._active_job_token = "job-123456789012"
    try:
        body = app.unload(_request())
        assert body["status"] == "ok"
        assert body["loaded"] is False
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        app._active_process = None
        app._active_job_token = ""


@pytest.mark.integration
def test_unload_token_khac_khong_duoc_kill_job_dang_chay():
    app = _load()
    app.API_TOKEN = "bi-mat-thu"
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    app._active_process = proc
    app._active_job_token = "job-123456789012"
    try:
        with pytest.raises(HTTPException) as caught:
            app.unload(_request(job_token="job-999999999999"))
        assert caught.value.status_code == 409
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=3)
        app._active_process = None
        app._active_job_token = ""


@pytest.mark.pure
def test_unload_job_pending_chan_popen_khoi_dong_sau_khi_da_nha_queue(monkeypatch):
    app = _load()
    app.API_TOKEN = "bi-mat-thu"
    app._active_job_token = "job-123456789012"
    app._active_process = None
    app._cancel_requested = False
    app._busy = True

    body = app.unload(_request())
    assert body["loaded"] is False
    assert app._cancel_requested is True

    monkeypatch.setattr(
        app.subprocess, "Popen",
        lambda *_a, **_k: pytest.fail("Popen không được chạy sau unload pending"))
    with pytest.raises(RuntimeError, match="đã bị hủy"):
        app._tach("input.wav", "/tmp", "job-123456789012")
    assert app._active_job_token == ""
    assert app._busy is False


@pytest.mark.pure
def test_track_nen_bi_cut_bi_tu_choi(monkeypatch):
    app = _load()
    durations = iter([100.0, 60.0])
    monkeypatch.setattr(app, "_thoi_luong", lambda _path: next(durations))
    with pytest.raises(RuntimeError, match="sai thời lượng"):
        app._kiem_tra_track_nen("input.wav", "background.wav")


@pytest.mark.integration
def test_ngat_khi_tai_wav_van_don_workspace_va_startup_don_orphan(tmp_path):
    app = _load()
    work = tmp_path / "fw-tach-am-response"
    work.mkdir()
    output = work / "background.wav"
    output.write_bytes(b"RIFF" + b"0" * 4096)
    response = app._FileResponseTuDon(
        str(output), work_dir=str(work), media_type="audio/wav")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("client ngắt")

    scope = {"type": "http", "method": "GET", "path": "/x",
             "headers": [], "query_string": b"", "scheme": "http",
             "http_version": "1.1", "server": ("test", 80),
             "client": ("test", 1)}
    with pytest.raises(OSError, match="client ngắt"):
        asyncio.run(response(scope, receive, send))
    assert not work.exists()

    orphan = tmp_path / "fw-tach-am-orphan"
    orphan.mkdir()
    (orphan / "huge.wav").write_bytes(b"x")
    other = tmp_path / "khong-phai-cua-service"
    other.mkdir()
    app._don_orphan(str(tmp_path))
    assert not orphan.exists()
    assert other.is_dir()
