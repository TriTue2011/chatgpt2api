/** Bật «nghe khi tắt màn hình» thì ai giữ tiếng.
 *
 * WebKit (iPhone, iPad, Safari) chỉ phát nổi tiếng YouTube trong khung nhúng.
 * Đưa sang thẻ âm thanh lúc khung còn chạy là hai bên tranh một suất: tiếng
 * xếp hàng mãi, hình bị dừng, bài kế cũng kẹt. Chrome và Android thì khung
 * không giữ được tiếng khi tắt màn, thẻ âm thanh thì được — nhưng phải câm
 * khung tại chỗ, không dựng lại.
 */
export type DuongTatMan = "giu-khung" | "chuyen-video" | "chuyen-loa" | "chi-co";

export function duongNgheKhiTatMan(o: {
  webkit: boolean;
  /** Đang mở khung YouTube (không phải hình riêng của Facebook). */
  coKhungYoutube: boolean;
  /** Tiếng đang ở trong khung, chưa giao cho thẻ âm thanh. */
  tiengTrongKhung: boolean;
  theoLoa: boolean;
}): DuongTatMan {
  if (o.webkit && o.coKhungYoutube && o.tiengTrongKhung) return "giu-khung";
  if (o.webkit) return "chi-co";
  if (o.coKhungYoutube && o.tiengTrongKhung && o.theoLoa) return "chuyen-loa";
  if (o.coKhungYoutube && o.tiengTrongKhung) return "chuyen-video";
  return "chi-co";
}

/** Mở video khi công tắc đã bật: WebKit để tiếng trong khung, máy khác để thẻ âm thanh. */
export function moVideoKhiTatMan(webkit: boolean): "khung" | "the-am" {
  return webkit ? "khung" : "the-am";
}
