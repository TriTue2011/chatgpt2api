"""Static regression contracts for the standalone Android avatar client."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stop_recording_stops_the_browser_recognition_instance():
    source = (ROOT / "android-ai-avatar" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);" in source
    assert "recognitionRef.current?.stop();" in source


def test_avatar_has_a_packaged_fallback_asset():
    root = ROOT / "android-ai-avatar"
    source = (root / "src" / "App.tsx").read_text(encoding="utf-8")

    assert 'src="/avatar.svg"' in source
    assert (root / "public" / "avatar.svg").is_file()


def test_failed_playback_stops_the_lip_sync_loop():
    """onended một mình là chưa đủ: play() bị chặn thì nó không bao giờ chạy,
    và vòng requestAnimationFrame cứ thế quay mãi."""
    source = (ROOT / "android-ai-avatar" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "audio.onerror = finish;" in source
    assert "audio.play().catch(finish);" in source
