"""Tải video từ LINK về máy, và GHÉP phụ đề vào khung hình.

Hai việc này là mắt xích duy nhất còn thiếu để một link YouTube đi trọn đường
"phụ đề / lồng tiếng" mà ``api/dich.py`` vốn đã làm được cho tệp tải lên.

Vì sao trước đây không có: ``video_dich`` cố ý đi bằng PHỤ ĐỀ SẴN CÓ của
YouTube — nhanh hơn tải video hàng trăm MB. Cách đó vẫn đúng khi người dùng chỉ
cần chữ. Nhưng khi họ muốn nhận lại VIDEO (chữ đốt sẵn trong hình, hoặc đã lồng
tiếng) thì bắt buộc phải có tệp hình trong tay. Trước module này, ô "lồng tiếng"
bị giấu khỏi link vì đúng lý do đó; nay link và tệp gửi lên đi chung một menu
(``dich_cho._viec_hop_le``).

Ai gọi: ``zalo_personal._lam_viec_dich`` — và chỉ gọi khi THẬT SỰ cần tệp hình
(ghép chữ, lồng tiếng, hoặc video không có phụ đề sẵn nên phải tự nghe).

Chủ máy chốt 18/08: KHÔNG giới hạn độ dài. Trần phân giải là 1080p (chốt lại
sau khi thấy 4K: bước đốt chữ vào hình vẽ lại TỪNG khung bằng CPU, nên 2160p
tốn gấp bốn lần 1080p cho một khác biệt không ai xem trong khung chat).
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


#: Hai mức tải. Chủ máy chốt 18/08: tải làm HAI bản chạy song song — bản VỪA
#: để máy xử lý (nghe, tách lời, tổng hợp giọng), bản CAO để ghép kết quả vào
#: rồi gửi người dùng. Bản CAO trần 1080p.
#:
#: Vì sao chia được mà không mất gì: yt-dlp chọn hình và tiếng RIÊNG, nên
#: trần chiều cao chỉ hạ luồng HÌNH — luồng TIẾNG vẫn là bản tốt nhất. Mà mọi
#: bước xử lý (nhận lời thoại, tách nhạc khỏi giọng, đo nhịp câu) đều chỉ nghe
#: chứ không nhìn. Bước duy nhất cần hình nét là bước cuối: đốt chữ vào khung
#: hoặc thay tiếng — làm trên bản CAO.
#:
#: Vì sao chạy song song: bản VỪA tải xong sớm hơn hẳn, máy bắt tay vào nghe
#: ngay trong lúc bản CAO còn đang tải. Trước đây phải chờ xong bản nặng nhất
#: rồi mới bắt đầu, tức cộng thẳng hai quãng thời gian vào nhau.
#: Vì sao trần 1080p chứ không lấy bản nét nhất có: bước đốt chữ vào khung
#: hình mã hoá lại TOÀN BỘ luồng hình bằng CPU, và chi phí đó đi theo số điểm
#: ảnh — 2160p là gấp bốn lần 1080p. Máy chủ mười nhân đang phục vụ thật, mà
#: người nhận thì xem trong khung chat điện thoại.
#:
#: Nhánh cuối mỗi dòng ('bestvideo*+bestaudio/best') là lưới đỡ cho nguồn
#: không có mức nào dưới trần: thà lấy bản nét hơn còn hơn không tải được gì.
CHAT_LUONG = {
    "cao": ("bestvideo[height<=1080]+bestaudio/"
            "best[height<=1080]/bestvideo*+bestaudio/best"),
    # 720p chứ không phải 480p, đo trên máy chủ 18/08: video_vision.trich_khung
    # ép mọi khung vào khung 768 điểm ảnh trước khi đưa Qwen. Nguồn 720p rộng
    # 1280 nên thu nhỏ 1,67 lần — ảnh sạch; nguồn 480p rộng 854, thu nhỏ 0,9
    # lần, tức nhiễu nén đi thẳng vào model (khung JPEG nhẹ hơn 11%, mất đúng
    # phần chi tiết mịn). Giá phải trả trên video 10 phút đã đo: 54 MB lên
    # 97 MB — vẫn nhẹ hơn 148 MB của bản 1080p nên vẫn về sớm hơn nó nhiều.
    "vua": ("bestvideo[height<=720]+bestaudio/"
            "best[height<=720]/bestvideo*+bestaudio/best"),
}


def tai_video(url: str, thu_muc: str | None = None, *,
              chat_luong: str = "cao") -> str:
    """Tải video về, trả đường dẫn tệp. Ném ``LoiTaiVideo`` nếu không được.

    ``chat_luong``: "cao" (mặc định, hình ≤1080p — bản đem gửi lại người dùng)
    hoặc "vua" (hình ≤720p — bản cho máy xử lý). Cả hai đều lấy luồng TIẾNG tốt
    nhất: trần chỉ đặt trên hình.

    KHÔNG chặn theo độ dài — chủ máy chốt 18/08 là tải mọi video, dài mấy cũng tải.
    """
    if chat_luong not in CHAT_LUONG:
        raise ValueError(f"chất lượng phải là {sorted(CHAT_LUONG)}, "
                         f"nhận {chat_luong!r}")
    if not co_yt_dlp():
        raise LoiTaiVideo(
            "Máy chủ chưa cài yt-dlp nên chưa tải được video về. "
            "Cần cài gói 'yt-dlp' rồi dựng lại image.")
    import yt_dlp

    dich = Path(thu_muc or tempfile.mkdtemp(prefix=f"tai_{chat_luong}_"))
    dich.mkdir(parents=True, exist_ok=True)
    tuy_chon = {
        "format": CHAT_LUONG[chat_luong],
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
    logger.info({"event": "video_tai_xong", "chat_luong": chat_luong,
                 "bytes": p.stat().st_size, "ten": p.name})
    return str(p)


class TaiSongSong:
    """Hai lượt tải CHẠY CÙNG LÚC: bản vừa để xử lý, bản cao để ghép.

    Dùng::

        tai = TaiSongSong(url)          # cả hai bắt đầu ngay
        xu_ly = tai.ban_vua()           # chờ bản nhẹ — về sớm
        ...nghe, dịch, tổng hợp giọng...
        ghep = tai.ban_cao() or xu_ly   # lúc này thường đã tải xong
        ...
        tai.dong()                      # xoá cả hai thư mục tạm

    ``ban_cao()`` trả "" khi bản cao hỏng, để việc vẫn xong trên bản vừa thay vì
    mất trắng: người dùng nhận video hơi mờ vẫn hơn nhận một câu báo lỗi.
    """

    def __init__(self, url: str) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self.url = url
        # Hai thư mục RIÊNG, tạo TRƯỚC khi tải: yt-dlp đặt tên tệp theo mã
        # video nên chung thư mục là hai lượt ghi đè nhau. Tạo trước còn để
        # ``dong()`` xoá được cả lượt tải chưa ai lấy kết quả — thường là bản
        # nét khi người dùng chỉ xin .srt.
        self._thu_muc = {muc: tempfile.mkdtemp(prefix=f"tai_{muc}_")
                         for muc in ("vua", "cao")}
        self._may = ThreadPoolExecutor(max_workers=2,
                                       thread_name_prefix="tai-video")
        self._viec = {muc: self._may.submit(tai_video, url, self._thu_muc[muc],
                                            chat_luong=muc)
                      for muc in ("vua", "cao")}

    def _lay(self, muc: str) -> str:
        return self._viec[muc].result()

    def ban_vua(self) -> str:
        """Bản nhẹ để xử lý. Hỏng thì ném ``LoiTaiVideo`` — không có nó thì
        không có gì để nghe, cả việc dừng ở đây."""
        return self._lay("vua")

    def ban_cao(self) -> str:
        """Bản nét để ghép kết quả vào. Hỏng thì trả "" (xem chú thích lớp)."""
        try:
            return self._lay("cao")
        except Exception as exc:
            logger.warning({"event": "tai_ban_cao_hong", "loi": str(exc)[:160]})
            return ""

    def dong(self) -> None:
        self._may.shutdown(wait=False, cancel_futures=True)
        for t in self._thu_muc.values():
            shutil.rmtree(t, ignore_errors=True)


def thay_tieng(duong_hinh: str, duong_tieng: str,
               duong_ra: str | None = None) -> str:
    """Lấy HÌNH của tệp này ghép với TIẾNG của tệp kia, trả đường dẫn tệp mới.

    Dùng để đưa kết quả lồng tiếng (làm trên bản vừa) lên bản phân giải cao:
    ``video_dub`` đã trộn xong giọng với nhạc nền rồi, việc còn lại chỉ là đổi
    khung hình. Chép nguyên cả hai luồng (``-c copy``) nên chạy vài giây bất kể
    video dài bao nhiêu — không mã hoá lại gì cả.
    """
    if not shutil.which("ffmpeg"):
        raise LoiTaiVideo("Máy chủ không có ffmpeg nên chưa ghép được tiếng.")
    hinh = Path(duong_hinh)
    ra = Path(duong_ra or hinh.with_name(f"{hinh.stem}_longtieng.mp4"))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(hinh), "-i", str(duong_tieng),
           "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
           "-movflags", "+faststart", str(ra)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not ra.exists():
        loi = (r.stderr or b"").decode("utf-8", "ignore")[-300:]
        raise LoiTaiVideo(f"Ghép tiếng vào bản nét hỏng: {loi}")
    logger.info({"event": "thay_tieng_xong", "bytes": ra.stat().st_size})
    return str(ra)


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
