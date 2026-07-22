/**
 * Hướng dẫn + link Google: App Password Gmail và TOTP Secret (Authenticator).
 * Dùng chung Settings (Codex/ChatGPT/Claude/Gemini/Flow) và import accounts.
 */

import { ExternalLink, Shield } from "lucide-react";

/** Tạo mật khẩu ứng dụng Gmail (bật 2FA trước). */
export const GMAIL_APP_PASSWORD_URL =
  "https://myaccount.google.com/apppasswords";

/** Bật xác minh 2 bước Google. */
export const GOOGLE_2FA_URL =
  "https://myaccount.google.com/signinoptions/two-step-verification";

/** Thêm Authenticator / lấy secret (setup app). */
export const GOOGLE_AUTHENTICATOR_URL =
  "https://myaccount.google.com/two-step-verification/authenticator";

function ExtLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-0.5 font-medium text-blue-700 underline decoration-blue-300 underline-offset-2 hover:text-blue-900"
    >
      {children}
      <ExternalLink className="size-3 shrink-0 opacity-70" />
    </a>
  );
}

/** Nhãn + link cạnh ô App Password Gmail. */
export function GmailAppPasswordLabel({
  className = "text-[10px] text-blue-800",
}: {
  className?: string;
}) {
  return (
    <label className={`${className} flex flex-wrap items-center gap-x-1.5 gap-y-0.5`}>
      <span>App Password Gmail</span>
      <ExtLink href={GMAIL_APP_PASSWORD_URL}>Tạo tại đây</ExtLink>
    </label>
  );
}

/** Gợi ý ngắn dưới ô App Password. */
export function GmailAppPasswordHint({
  className = "text-[10px] text-blue-800/80 mt-1 leading-relaxed",
}: {
  className?: string;
}) {
  return (
    <p className={className}>
      Cần bật{" "}
      <ExtLink href={GOOGLE_2FA_URL}>xác minh 2 bước</ExtLink>
      {" "}trước. Vào{" "}
      <ExtLink href={GMAIL_APP_PASSWORD_URL}>Mật khẩu ứng dụng</ExtLink>
      {" "}→ chọn Ứng dụng / Thiết bị → Tạo → copy 16 ký tự (dạng{" "}
      <code className="rounded bg-blue-100/80 px-1">abcd efgh ijkl mnop</code>
      ) dán vào đây. Không dùng mật khẩu đăng nhập Gmail thường.
    </p>
  );
}

/** Nhãn TOTP Secret + link tạo. */
export function TotpSecretLabel({
  className = "text-[11px] text-[var(--muted-foreground)]",
}: {
  className?: string;
}) {
  return (
    <label className={`${className} flex flex-wrap items-center gap-x-1.5 gap-y-0.5`}>
      <Shield className="size-3 shrink-0" />
      <span>TOTP Secret (để trống = xác minh thiết bị)</span>
      <ExtLink href={GOOGLE_AUTHENTICATOR_URL}>Mở chỗ tạo Authenticator</ExtLink>
    </label>
  );
}

/**
 * Hướng dẫn chi tiết lấy secret khi Google hiện QR.
 * User: quét bằng ĐT nhưng KHÔNG bấm Tiếp — bấm “Không quét được QR” để copy mã.
 */
export function TotpSecretGuide({
  className = "mt-1.5 rounded-lg border border-amber-200/80 bg-amber-50/70 p-2.5 text-[10px] text-amber-950/90 leading-relaxed space-y-1.5",
}: {
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="font-semibold text-amber-900">
        Cách lấy secret dán vào đây (khi Google hiện mã QR Authenticator)
      </p>
      <ol className="list-decimal pl-3.5 space-y-1">
        <li>
          Mở{" "}
          <ExtLink href={GOOGLE_2FA_URL}>Xác minh 2 bước</ExtLink>
          {" "}→{" "}
          <ExtLink href={GOOGLE_AUTHENTICATOR_URL}>Ứng dụng Authenticator</ExtLink>
          {" "}→ Thiết lập / Thêm Authenticator.
        </li>
        <li>
          Khi màn hình hiện <b>mã QR</b>: có thể dùng điện thoại quét để gắn app
          Authenticator, nhưng <b className="text-red-700">chưa nhấn Tiếp / Next</b>{" "}
          trên web.
        </li>
        <li>
          Trên cùng màn hình QR, bấm link kiểu{" "}
          <b>«Không thể quét mã QR?»</b> /{" "}
          <b>«Can&apos;t scan it?»</b> /{" "}
          <b>«Can&apos;t scan the barcode?»</b> — Google hiện{" "}
          <b>chuỗi secret</b> (dạng chữ/số dài, thường nhóm 4 ký tự).
        </li>
        <li>
          <b>Copy</b> nguyên chuỗi đó → <b>dán vào ô TOTP Secret</b> trên
          chatgpt2api (trang này).
        </li>
        <li>
          Sau khi đã dán secret xong, mới quay lại trang Google → nhấn{" "}
          <b>Tiếp / Next</b> → nhập mã 6 số (từ app Authenticator hoặc mã hiện
          bên dưới ô secret nếu hệ thống đã sinh) để xác thực theo yêu cầu trên
          web.
        </li>
      </ol>
      <p className="text-amber-900/80 pt-0.5">
        <b>Để trống</b> ô secret = khi login Google sẽ dùng xác minh thiết bị
        (tap trên điện thoại / prompt), không tự sinh mã Authenticator.
      </p>
    </div>
  );
}
