"""Chạy việc người dùng đã chọn trong menu video, cho MỌI kênh chat.

Tách khỏi ``zalo_personal`` 18/08 vì Telegram cần đúng những lựa chọn ấy. Trước
đó menu bảy ô chỉ Zalo cá nhân có; Telegram nhận video là tự nghe rồi trả .srt
tiếng Việt, không hỏi gì — không phải quyết định nào cả, chỉ là chỗ chưa nối.

Chép sang kênh thứ hai thì hai bản sẽ lệch nhau ngay lần sửa đầu tiên, nên phần
NGHIỆP VỤ nằm ở đây, còn mỗi kênh chỉ đưa vào bốn cửa gửi ra của mình (``Kenh``).
Bốn cửa đó là toàn bộ khác biệt giữa Zalo và Telegram trong việc này.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from services import video_tai

logger = logging.getLogger(__name__)


@dataclass
class Kenh:
    """Cửa gửi ra của một kênh chat.

    ``gui_tra_loi`` tách riêng khỏi ``gui_tin`` vì mỗi kênh xử lý bài dài một
    kiểu: Zalo cắt tin ở 2.000 ký tự nên câu trả lời dài được đóng thành .docx,
    Telegram cắt ở 4.096 và tự chia khúc. Trả True nghĩa là kênh đã lo xong.
    """

    gui_tin: Callable[[str], None]
    gui_bytes: Callable[[bytes, str, str], None]
    gui_tep: Callable[[str, str, str], None]
    dang_go: Callable[[], None] = lambda: None
    gui_tra_loi: Callable[[str], bool] = lambda chu: False


def _tai_video_ve(kenh: Kenh, url: str, chat_luong: str = "cao") -> str:
    """Tải video của một link về máy. Trả đường dẫn, hoặc "" khi hỏng (đã báo).

    Chỉ gọi khi thật sự cần TỆP HÌNH (ghép chữ vào khung, lồng tiếng, hoặc
    video không có phụ đề sẵn). Đường phụ đề-sẵn-có của ``video_dich`` nhanh
    hơn nhiều nên vẫn là đường mặc định cho các ô chỉ cần chữ.

    ``chat_luong="vua"`` khi chỉ cần NGHE: hạ luồng hình xuống ≤720p, luồng
    tiếng vẫn là bản tốt nhất nên chữ nhận ra không đổi, mà tải nhanh hơn nhiều.
    """
    from services import video_tai as _vt

    kenh.gui_tin("⬇️ Em tải video về đã, video dài thì mất vài phút ạ…")
    kenh.dang_go()
    try:
        return _vt.tai_video(url, chat_luong=chat_luong)
    except _vt.LoiTaiVideo as exc:
        kenh.gui_tin(f"⚠️ {exc}")
    except Exception as exc:
        logger.warning("video_giao tải video lỗi: %s", str(exc)[:200])
        kenh.gui_tin(f"⚠️ Không tải được video: {str(exc)[:200]}")
    return ""


def _cho_ban_vua(kenh: Kenh, tai: video_tai.TaiSongSong) -> str:
    """Chờ bản NHẸ của hai lượt tải song song. Trả "" khi hỏng (đã báo).

    Bản nhẹ hỏng là cả việc dừng: không có tệp thì không nghe được gì. Bản nét
    hỏng thì khác — ``TaiSongSong.ban_cao`` trả "" và việc vẫn xong trên bản nhẹ.
    """
    from services import video_tai as _vt

    kenh.dang_go()
    try:
        return tai.ban_vua()
    except _vt.LoiTaiVideo as exc:
        kenh.gui_tin(f"⚠️ {exc}")
    except Exception as exc:
        logger.warning("video_giao chờ bản tải nhẹ lỗi: %s", str(exc)[:200])
        kenh.gui_tin(f"⚠️ Không tải được video: {str(exc)[:200]}")
    return ""


def _tra_loi_tu_phu_de(kenh: Kenh, r: dict, chon: dict) -> None:
    """Bốn ô đọc-hiểu: tóm tắt · ý chính · phân tích đoạn · ghi chú.

    Chủ máy chốt 18/08: "chuyển thành phụ đề rồi mới qua llm để làm 12345" —
    nên hàm này KHÔNG nghe lại video, nó nhận kết quả phụ đề đã có trong tay.
    """
    from services import video_dich as _vd
    from services import video_hoi as _vh

    if not r.get("ok"):
        kenh.gui_tin(_vd.bao_cao(r))
        return
    viec = str(chon.get("viec") or "")
    # Ô phân tích cần MỐC GIỜ để tìm đúng đoạn người dùng nêu ("từ 10:20"); ba
    # ô còn lại chỉ cần lời thoại — số thứ tự và mốc giờ của .srt chỉ tổ ăn chỗ
    # trong cửa sổ ngữ cảnh mà không thêm nghĩa nào.
    noi_dung = (r["srt"].decode("utf-8") if viec in _vh.CAN_MOC_GIO
                else str(r.get("chu") or ""))
    kenh.gui_tin("🧠 Có phụ đề rồi, em đọc và trả lời ngay ạ…")
    kenh.dang_go()
    try:
        tra_loi = _vh.hoi(viec, noi_dung, them=str(chon.get("doan") or ""))
    except Exception as exc:
        logger.warning("video_giao đọc phụ đề lỗi: %s", str(exc)[:200])
        kenh.gui_tin(f"⚠️ Em lấy được phụ đề nhưng chưa trả lời được: "
                     f"{str(exc)[:200]}")
        # Gửi kèm phụ đề: nghe cả video xong mà mất trắng vì model bận thì lần
        # sau người dùng phải chờ lại từ đầu.
        kenh.gui_bytes(r["srt"], r["ten"], "Phụ đề (để không mất kết quả)")
        return
    if not kenh.gui_tra_loi(tra_loi):
        kenh.gui_tin(tra_loi)


def chay(kenh: Kenh, pend: dict | None, chon: dict) -> None:
    """Chạy việc dịch theo lựa chọn người dùng vừa bấm trong menu.

    Ba nguồn (chữ / link / tệp) × hai kiểu kết quả (.srt / bản chữ) × tiếng đích
    — tất cả do NGƯỜI DÙNG chọn, không đoán. Xem services/dich_cho.py.
    """
    from services import dich_cho as _dc
    from services import translate_service as _ts
    from services import video_dich as _vd

    if not pend:
        return
    kieu = str(chon.get("kieu") or "phu-de")
    target = _dc.target_cho_may(chon)
    # Mọi tệp DO EM DỰNG RA trong lượt này (video tải về, bản đã ghép chữ, bản
    # lồng tiếng) — xoá hết ở finally. Tệp người dùng gửi lên thì không nằm đây:
    # nó do _dc.don_tep(pend) dọn.
    tep_tam: list[str] = []
    # Khai TRƯỚC try: khối finally đọc biến này, mà nhánh "đoạn chữ" thoát ra
    # trước khi tới chỗ gán thì finally sẽ nổ NameError thay vì dọn dẹp.
    tai = None
    try:
        # ── Chữ: dịch ngay, không có chuyện phụ đề ───────────────────────────
        if _dc.la_chu(pend):
            nd = str(pend.get("chu") or "")
            ma = target[4:] if target.startswith("cap:") else (target or "")
            try:
                nguon, _ = _ts.detect(nd[:5000])
                dich = _ts.giai_ma_target(nguon, target)
                if nguon and nguon == dich:
                    kenh.gui_tin(f"🌐 Đoạn này đã là tiếng `{dich}` rồi ạ.")
                    return
                ban = _ts.translate(nd, dich, nguon or "auto")
            except _ts.LoiDich as exc:
                kenh.gui_tin(f"🌐 Máy dịch lỗi: {exc}")
                return
            # Dài thì đóng .docx SONG NGỮ: gửi thẳng là Zalo cắt thành hàng chục
            # tin (2000 ký tự/tin) và mất đường đối chiếu với bản gốc đúng lúc
            # cần nhất — khi máy dịch hiểu sai một câu.
            from services import song_ngu as _sn
            goi = _sn.dong_goi(nd, ban, nguon=nguon or "auto", dich=dich,
                               tieu_de="Bản dịch song ngữ")
            if goi.get("tep"):
                kenh.gui_tin(f"🌐 {nguon or 'auto'} → {dich} · bản dài nên em "
                             "đóng thành tệp song ngữ ạ.")
                kenh.gui_bytes(goi["tep"], goi["ten"], "Bản dịch song ngữ")
                return
            kenh.gui_tin(f"🌐 {nguon or 'auto'} → {dich}\n{ban}")
            return

        # ── Link / tệp: phụ đề · bản chữ · video · câu trả lời của LLM ──────
        from services import video_tai as _vt

        dang_ra = str(chon.get("dang_ra") or "")
        vi_tri = str(chon.get("vi_tri") or "duoi")
        # Hai việc cần TỆP HÌNH trong tay: đốt chữ vào khung, và thay tiếng.
        # Ô .srt thì không — tải mấy trăm MB về để trả một tệp chữ là phí.
        can_video = kieu == "long-tieng" or (kieu == "phu-de" and dang_ra == "ghep")
        if kieu == "long-tieng":
            from services import tach_am_gpu as _tach_am

            try:
                _tach_am.xac_nhan_san_sang()
            except _tach_am.LoiTachAm as exc:
                kenh.gui_tin(
                    f"⚠️ Chưa lồng tiếng được: {exc}.\nKhông có GPU tách lời "
                    "thì em chỉ tạo được PHỤ ĐỀ thôi ạ — anh gửi lại rồi chọn "
                    "mục 6 nhé.")
                return
        # Bản VỪA để máy xử lý (nghe, tách lời, tổng hợp giọng), bản CAO để
        # ghép kết quả vào rồi gửi lại. Tệp gửi lên thì chỉ có một bản, dùng
        # chung cho cả hai việc.
        duong_xu_ly = str(pend.get("path") or "")
        if can_video and pend.get("url"):
            if not _vt.co_yt_dlp():
                kenh.gui_tin("⚠️ Máy chủ chưa cài yt-dlp nên chưa tải được "
                             "video về. Anh chọn lại mục 6 rồi lấy tệp .srt "
                             "thì em vẫn làm được ạ.")
                return
            # Bật CẢ HAI lượt tải ngay từ đây, trước cả bước lấy phụ đề: lấy
            # phụ đề YouTube chỉ mất vài giây, để đường truyền nằm không trong
            # lúc đó là phí đúng quãng dài nhất của cả việc.
            tai = _vt.TaiSongSong(str(pend["url"]))
            kenh.gui_tin("⬇️ Em tải video về, hai bản chạy song song: bản nhẹ "
                         "để xử lý cho nhanh, bản nét để gửi lại anh ạ.")
        kenh.gui_tin("🎬 Em làm ngay, video dài có thể mất vài phút ạ…")
        kenh.dang_go()
        # "giu-goc" = chép lời, không dịch: truyền cờ để tầng dưới đặt
        # đích = chính tiếng nguồn sau khi đã nghe/đọc ra tiếng đó.
        # Bốn ô LLM cũng chép lời: model đọc được tiếng gốc, dịch trước chỉ tốn
        # thêm một lượt máy dịch và thêm một chỗ cho nghĩa trượt đi.
        _tg = "" if target == "giu-goc" else target
        _chep = target == "giu-goc" or kieu == "llm"
        # Chat không có thanh tiến độ và Zalo không cho sửa tin đã gửi (bot
        # server chỉ có `undo`), nên chỉ nhắn ở MỐC chuyển giai đoạn. Báo
        # từng lô dịch là mười mấy tin nhắn cho một video.
        _so_moc = 0

        def _tien_do_zalo(buoc: str, _phan_tram: int | None, moc: bool) -> None:
            nonlocal _so_moc
            if not moc:
                return
            _so_moc += 1
            # Mốc đầu là "đang bóc tiếng", mà câu "Em làm ngay…" ở trên vừa
            # nói đúng điều đó — nhắn lại là hai tin dính nhau cùng một nghĩa.
            if _so_moc > 1:
                kenh.gui_tin(f"⏳ {buoc}")

        def _nghe_tep_tai_ve() -> dict:
            # Người dùng đã nói rõ tệp nói tiếng gì ở bước 2 → khoá cứng model
            # nghe, khỏi dò. Dò là mỗi tiếng ứng viên thêm một lượt nghe.
            return _vd.dich_tep_video(duong_xu_ly,
                                      ten_goc or Path(duong_xu_ly).name, _tg,
                                      chep_loi=_chep,
                                      nguon_biet=str(chon.get("nguon") or ""),
                                      tien_do=_tien_do_zalo)

        ten_goc = str(pend.get("ten") or "")
        if _vd.la_tep_phu_de(ten_goc):
            r = _vd.dich_tep_phu_de(pend["path"], ten_goc, _tg, chep_loi=_chep)
        elif pend.get("url"):
            # Phụ đề SẴN CÓ của YouTube trước đã: nó khớp đúng khung hình, lấy
            # trong vài giây, và khỏi nghe lại cả video. Tải hình về chỉ để ghép
            # chữ / thay tiếng, và làm SAU khi chắc chắn có phụ đề — hỏng ở bước
            # chữ mà đã tải mấy trăm MB thì phí trắng.
            #
            # Bước 2 đã hỏi video nói tiếng gì → khoá việc chọn phụ đề vào đúng
            # tiếng đó. Bỏ câu trả lời ở đây thì video có cả bản Nhật lẫn bản
            # Anh vẫn có thể bị lấy bản Anh rồi dịch tiếp — dịch hai lần qua ba
            # thứ tiếng, đúng lỗi đã đo ở đường web.
            r = _vd.dich_video(pend["url"], _tg, chep_loi=_chep,
                               nguon_biet=str(chon.get("nguon") or ""))
            if not r.get("ok") and _vd.thieu_phu_de_san(r):
                # Không có phụ đề sẵn thì tải hình về rồi TỰ NGHE — việc mà
                # video_dich.LOI_CHUA_CO_TIENG từng ghi là "chưa làm". Chỉ cần
                # bản VỪA: nghe là việc của luồng tiếng, mà luồng tiếng của bản
                # vừa vẫn là bản tốt nhất.
                kenh.gui_tin("🎬 Video này không có phụ đề sẵn, em tải về nghe "
                             "trực tiếp nhé — lâu hơn một chút ạ.")
                if tai is None:
                    duong_xu_ly = _tai_video_ve(kenh, str(pend["url"]),
                                                "vua")
                    if not duong_xu_ly:
                        return
                    tep_tam.append(duong_xu_ly)
                else:
                    duong_xu_ly = _cho_ban_vua(kenh, tai)
                    if not duong_xu_ly:
                        return
                r = _nghe_tep_tai_ve()
        else:
            r = _nghe_tep_tai_ve()
        if (tai is not None and not duong_xu_ly and r.get("ok")
                and kieu == "long-tieng"):
            # Chỉ LỒNG TIẾNG mới cần tệp hình để xử lý (tách nhạc khỏi giọng,
            # đo nhịp từng câu). Ghép chữ thì không: phụ đề đã có trong tay,
            # việc còn lại là đốt nó lên bản nét. Chờ ở đây cũng là chờ thứ
            # mình không dùng.
            duong_xu_ly = _cho_ban_vua(kenh, tai)
            if not duong_xu_ly:
                return

        # ── Bốn ô đọc-hiểu: phụ đề vừa xong là ĐẦU VÀO cho LLM ──────────────
        # Chủ máy chốt 18/08: "chuyển thành phụ đề rồi mới qua llm để làm 12345".
        if kieu == "llm":
            _tra_loi_tu_phu_de(kenh, r, chon)
            return

        if kieu == "long-tieng" and r.get("ok") and not r.get("canh_bao_dich"):
            from services import video_dub as _dub

            kenh.gui_tin("🔊 Đã có phụ đề, em đang tách lời gốc để giữ nhạc/hiệu ứng, "
                         "sau đó tổng hợp giọng và ghép video…")
            try:
                giong = _dub.chon_giong(str(r.get("dich") or ""))
                dub = _dub.long_tieng(duong_xu_ly, r["srt"], str(r["dich"]),
                                      voice=giong)
                tep_tam.extend([dub.video_path, dub.prosody_path])
                video_gui = dub.video_path
                ban_net = tai.ban_cao() if tai is not None else ""
                if ban_net:
                    # Giọng đã trộn xong với nhạc nền trên bản vừa; giờ đổi
                    # khung hình sang bản nét. Chép nguyên cả hai luồng nên
                    # mất vài giây, không mã hoá lại gì.
                    #
                    # Hỏng ở đây KHÔNG được kéo cả lượt xuống: phần đắt nhất
                    # (tách lời, tổng hợp giọng, trộn nhạc) đã xong rồi, mất nó
                    # vì một bước chép luồng là quá phí. Gửi bản vừa đã lồng
                    # tiếng, chỉ nói rõ là hình không nét bằng.
                    try:
                        video_gui = _vt.thay_tieng(ban_net, dub.video_path)
                        tep_tam.append(video_gui)
                    except Exception as exc_net:
                        logger.warning("video_giao đổi sang bản nét lỗi: %s",
                                       str(exc_net)[:200])
                        kenh.gui_tin("⚠️ Em lồng tiếng xong nhưng chưa đưa lên "
                                     "được bản nét, nên gửi anh bản hình nhẹ "
                                     "hơn ạ.")
            except Exception as exc:
                logger.warning("video_giao lồng tiếng lỗi: %s", str(exc)[:200])
                kenh.gui_tin(
                    _vd.bao_cao(r) + "\n⚠️ Lồng tiếng không hoàn thành: "
                    + str(exc)[:220] + "; em vẫn gửi SRT để không mất kết quả.")
                kenh.gui_bytes(r["srt"], r["ten"], "Phụ đề")
                return
            kenh.gui_tin(
                _vd.bao_cao(r) + f"\n🔊 Đã lồng bằng {dub.voice}; track âm "
                "thanh gốc không được dùng, TTS đã trộn với stem nhạc/hiệu ứng."
                " Source separation có thể còn rò giọng ở cảnh âm thanh chồng "
                "lấn." + (f"\n⚠️ {dub.canh_bao}" if dub.canh_bao else ""))
            kenh.gui_tep(video_gui, f"long-tieng.{r['dich']}.mp4",
                         "Video đã lồng tiếng")
            kenh.gui_tep(dub.prosody_path, f"prosody.{r['dich']}.json",
                         "Nhịp và giọng từng câu")
            kenh.gui_bytes(r["srt"], r["ten"], "Phụ đề")
            return
        kenh.gui_tin(_vd.bao_cao(r))
        if not r.get("ok"):
            return
        if kieu == "chu":
            from services import song_ngu as _sn
            # KHÔNG dịch (chép lời ra bản chữ — chính là việc người dùng gọi là
            # STT): ngắn thì nhắn thẳng, dài thì đóng .docx cho dán được vào tài
            # liệu. Không kèm .txt nữa: hai tệp cùng nội dung chỉ tổ rối.
            if target == "giu-goc":
                if _sn.nen_dong_tep(r["chu"]):
                    kenh.gui_bytes(
                        _sn.docx_mot_ban(
                            r["chu"], tieu_de="Bản chép lời",
                            ghi_chu=f"Tiếng {r.get('nguon') or '?'}"),
                        f"chep-loi.{r.get('nguon') or 'goc'}.docx",
                        "Bản chép lời")
                else:
                    kenh.gui_tin(r["chu"])
                return
            kenh.gui_bytes(r["chu"].encode("utf-8"),
                           f"loi-thoai.{r['dich']}.txt", "Bản chữ lời thoại")
            # Có dịch và lời thoại dài → kèm bản SONG NGỮ để đối chiếu được câu
            # nào máy dịch hiểu sai.
            cap = r.get("song_ngu") or []
            if cap and r.get("nguon") != r.get("dich") and _sn.nen_dong_tep(r["chu"]):
                try:
                    kenh.gui_bytes(
                        _sn.docx_song_ngu(cap, nguon=r.get("nguon", ""),
                                          dich=r.get("dich", ""),
                                          tieu_de="Lời thoại song ngữ"),
                        f"song-ngu.{r['dich']}.docx", "Lời thoại song ngữ")
                except Exception as exc:
                    logger.info("đóng lời thoại song ngữ lỗi: %s", str(exc)[:120])
            if len(r["chu"]) <= 1500:
                kenh.gui_tin(r["chu"])
            return

        # ── Ô phụ đề: MỘT tệp duy nhất, đúng vị trí và đúng dạng đã chọn ─────
        # Bản cũ gửi CẢ HAI tệp .srt (bản thường + bản chữ-trên) vì không hỏi.
        # Chủ máy chốt 18/08: "nếu phụ đề kèm 2 lựa chọn bên trên hay bên dưới,
        # KHÔNG gửi 2 cái như bây giờ".
        srt_chu = r["srt"].decode("utf-8")
        if vi_tri == "tren":
            srt_chu = _vd.srt_chu_tren(srt_chu)
        if dang_ra == "ghep":
            # Đốt chữ lên bản NÉT — đây là bước duy nhất cần hình đẹp. Bản nét
            # hỏng thì vẫn đốt lên bản vừa: video hơi mờ vẫn hơn không có gì.
            ban_net = (tai.ban_cao() if tai is not None else "") or duong_xu_ly
            if not ban_net:
                # Cả hai bản đều không về được. Vẫn còn phụ đề trong tay nên
                # gửi nó, đừng để cả lượt thành công cốc.
                kenh.gui_tin("⚠️ Em không tải được video về nên chưa đốt chữ "
                             "vào hình được. Em gửi tệp .srt để không mất kết "
                             "quả ạ.")
                kenh.gui_bytes(srt_chu.encode("utf-8"), r["ten"], "Phụ đề")
                return
            try:
                # Ghép thì đưa .srt GỐC: vị trí đã do force_style Alignment lo
                # (video_tai.VI_TRI). Thêm thẻ {\an8} vào nữa là hai đường cùng
                # nói một điều, và chỉ cần một đường đổi ý là lệch nhau.
                video_ra = _vt.ghep_phu_de(ban_net, r["srt"], vi_tri)
            except Exception as exc:
                logger.warning("video_giao ghép phụ đề lỗi: %s", str(exc)[:200])
                kenh.gui_tin(f"⚠️ Ghép chữ vào video hỏng: {str(exc)[:200]}\n"
                             "Em gửi tệp .srt để không mất kết quả ạ.")
                kenh.gui_bytes(srt_chu.encode("utf-8"), r["ten"], "Phụ đề")
                return
            tep_tam.append(video_ra)
            kenh.gui_tep(video_ra, f"phu-de-{vi_tri}.{r['dich']}.mp4",
                         "Video đã ghép chữ ở "
                         + ("MÉP TRÊN" if vi_tri == "tren" else "mép dưới"))
            return
        kenh.gui_bytes(
            srt_chu.encode("utf-8"),
            r["ten"] if vi_tri == "duoi" else f"phu-de-tren.{r['dich']}.srt",
            "Phụ đề" + (" — chữ hiện ở MÉP TRÊN" if vi_tri == "tren" else ""))
    finally:
        if tai is not None:
            tai.dong()
        for p in tep_tam:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        _dc.don_tep(pend)
