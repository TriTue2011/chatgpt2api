"""Tải video từ LINK về máy, và GHÉP phụ đề vào khung hình.

Hai việc này là mắt xích duy nhất còn thiếu để một link YouTube đi trọn đường
"phụ đề / lồng tiếng" mà ``api/dich.py`` vốn đã làm được cho tệp tải lên.

Vì sao trước đây không có: ``video_dich`` cố ý đi bằng PHỤ ĐỀ SẴN CÓ của
YouTube — nhanh hơn tải video hàng trăm MB. Cách đó vẫn đúng khi người dùng chỉ
cần chữ. Nhưng khi họ muốn nhận lại VIDEO (chữ đốt sẵn trong hình, hoặc đã lồng
tiếng) thì bắt buộc phải có tệp hình trong tay — chú thích trong
``dich_cho.VIEC`` ghi rõ ô "lồng tiếng" chỉ hiện cho tệp video vì "link hiện
chưa tải cả hình về gateway".

Chủ máy chốt 18/08: KHÔNG giới hạn độ dài, tải ở ĐỘ PHÂN GIẢI CAO NHẤT.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: Vị trí chữ khi ghép vào hình. Số là mã căn lề của ASS/libass:
#: 2 = giữa-dưới, 8 = giữa-trên. Cùng quy ước với thẻ ``{\an8}`` mà
#: ``video_dich.srt_chu_tren`` dùng cho tệp .srt rời.
VI_TRI = {"duoi": 2, "tren": 8}


class LoiTaiVideo(RuntimeError):
    """Không tải được video — người gọi báo lại nguyên văn cho người dùng."""


def co_yt_dlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def tai_video(url: str, thu_muc: str | None = None) -> str:
    """Tải video về, trả đường dẫn tệp. Ném ``LoiTaiVideo`` nếu không được.

    Chọn luồng hình TỐT NHẤT rồi ghép với luồng tiếng tốt nhất; không có bản
    tách luồng thì lấy bản gộp sẵn tốt nhất. KHÔNG chặn theo độ dài — chủ máy
    chốt 18/08 là tải mọi video, dài mấy cũng tải.
    """
    if not co_yt_dlp():
        raise LoiTaiVideo(
            "Máy chủ chưa cài yt-dlp nên chưa tải được video về. "
            "Cần cài gói 'yt-dlp' rồi dựng lại image.")
    import yt_dlp

    dich = Path(thu_muc or tempfile.mkdtemp(prefix="tai_video_"))
    dich.mkdir(parents=True, exist_ok=True)
    tuy_chon = {
        # bestvideo+bestaudio = độ phân giải cao nhất; 'best' đứng sau làm lưới
        # đỡ cho nguồn không tách luồng.
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": str(dich / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(tuy_chon) as ydl:
            tin = ydl.extract_info(url, download=True)
            duong = ydl.prepare_filename(tin)
    except Exception as exc:
        raise LoiTaiVideo(f"Không tải được video: {str(exc)[:200]}") from exc

    p = Path(duong)
    if not p.exists():
        # merge_output_format đổi đuôi → tìm lại theo mã video.
        ung = sorted(dich.glob(f"{tin.get('id', '*')}.*"))
        if not ung:
            raise LoiTaiVideo("Tải xong nhưng không thấy tệp video đâu.")
        p = ung[0]
    logger.info({"event": "video_tai_xong", "bytes": p.stat().st_size,
                 "ten": p.name})
    return str(p)


def ghep_phu_de(duong_video: str, srt: str | bytes, vi_tri: str = "duoi",
                duong_ra: str | None = None) -> str:
    """Đốt phụ đề vào khung hình, trả đường dẫn video mới.

    ``vi_tri``: "duoi" (mặc định) hoặc "tren".

    Vì sao đốt cứng chứ không gắn luồng phụ đề mềm: người dùng nhận video qua
    Zalo/Telegram rồi xem ngay trong ứng dụng chat — các trình phát đó KHÔNG
    cho bật/tắt phụ đề mềm, nên chữ mềm coi như không tồn tại.

    Chỉ mã hoá lại luồng HÌNH; luồng TIẾNG chép nguyên (``-c:a copy``) cho nhanh
    và không hao chất lượng.
    """
    if vi_tri not in VI_TRI:
        raise ValueError(f"vị trí phải là {sorted(VI_TRI)}, nhận {vi_tri!r}")
    if not shutil.which("ffmpeg"):
        raise LoiTaiVideo("Máy chủ không có ffmpeg nên chưa ghép được phụ đề.")

    goc = Path(duong_video)
    ra = Path(duong_ra or goc.with_name(f"{goc.stem}_phude{goc.suffix or '.mp4'}"))
    noi_dung = srt.encode("utf-8") if isinstance(srt, str) else srt
    tam = Path(tempfile.mkdtemp(prefix="phu_de_"))
    tep_srt = tam / "phu_de.srt"
    tep_srt.write_bytes(noi_dung)

    # Dấu ':' và '\' trong đường dẫn làm hỏng cú pháp bộ lọc → dùng đường
    # tương đối trong chính thư mục tạm để khỏi phải thoát ký tự.
    style = (f"FontSize=22,Alignment={VI_TRI[vi_tri]},"
             "BorderStyle=1,Outline=2,Shadow=0,MarginV=28")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(goc),
           "-vf", f"subtitles=phu_de.srt:force_style='{style}'",
           "-c:a", "copy", str(ra)]
    r = subprocess.run(cmd, cwd=str(tam), capture_output=True)
    if r.returncode != 0 or not ra.exists():
        loi = (r.stderr or b"").decode("utf-8", "ignore")[-300:]
        raise LoiTaiVideo(f"Ghép phụ đề hỏng: {loi}")
    logger.info({"event": "phu_de_ghep_xong", "vi_tri": vi_tri,
                 "bytes": ra.stat().st_size})
    return str(ra)
