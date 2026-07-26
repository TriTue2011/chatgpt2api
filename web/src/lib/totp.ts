/**
 * RFC 6238 TOTP generator (SHA-1, 30s, 6 chữ số) — tương thích Google Authenticator.
 *
 * QUAN TRỌNG: `crypto.subtle` CHỈ tồn tại trong "secure context" (HTTPS hoặc
 * localhost). Mở giao diện quản trị bằng IP qua HTTP thường (vd
 * http://172.16.10.38:3030) thì `crypto.subtle` là undefined → trước đây hàm ném
 * lỗi và ô mã TOTP im lặng trống rỗng. Vì vậy có bản HMAC-SHA1 thuần JS làm dự
 * phòng: dùng Web Crypto khi có, không có thì tự tính. Secret KHÔNG rời trình duyệt.
 */

const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32Decode(input: string): Uint8Array {
  const clean = input.replace(/\s/g, "").toUpperCase();
  let bits = "";
  for (const ch of clean) {
    const val = BASE32_ALPHABET.indexOf(ch);
    if (val === -1) continue;
    bits += val.toString(2).padStart(5, "0");
  }
  const byteLen = Math.floor(bits.length / 8);
  const bytes = new Uint8Array(byteLen);
  for (let i = 0; i < byteLen; i++) {
    bytes[i] = parseInt(bits.substring(i * 8, i * 8 + 8), 2);
  }
  return bytes;
}

function counterBytes(): Uint8Array {
  const counter = Math.floor(Date.now() / 1000 / 30);
  const buf = new ArrayBuffer(8);
  new DataView(buf).setBigUint64(0, BigInt(counter), false);
  return new Uint8Array(buf);
}

/** SHA-1 thuần JS → 20 byte. Chỉ dùng khi không có Web Crypto. */
function sha1(msg: Uint8Array): Uint8Array {
  const ml = msg.length;
  const withPad = new Uint8Array((((ml + 8) >> 6) + 1) << 6);
  withPad.set(msg);
  withPad[ml] = 0x80;
  const view = new DataView(withPad.buffer);
  view.setUint32(withPad.length - 4, ml * 8, false);

  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Uint32Array(80);

  for (let off = 0; off < withPad.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4, false);
    for (let i = 16; i < 80; i++) {
      const n = w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16];
      w[i] = (n << 1) | (n >>> 31);
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i++) {
      let f: number, k: number;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const t = (((a << 5) | (a >>> 27)) + f + e + k + w[i]) >>> 0;
      e = d; d = c; c = ((b << 30) | (b >>> 2)) >>> 0; b = a; a = t;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  const out = new Uint8Array(20);
  const ov = new DataView(out.buffer);
  [h0, h1, h2, h3, h4].forEach((h, i) => ov.setUint32(i * 4, h, false));
  return out;
}

/** HMAC-SHA1 thuần JS (block 64 byte, RFC 2104). */
function hmacSha1Pure(keyBytes: Uint8Array, msg: Uint8Array): Uint8Array {
  const key = keyBytes.length > 64 ? sha1(keyBytes) : keyBytes;
  const pad = new Uint8Array(64);
  pad.set(key);
  const inner = new Uint8Array(64 + msg.length);
  const outer = new Uint8Array(64 + 20);
  for (let i = 0; i < 64; i++) {
    inner[i] = pad[i] ^ 0x36;
    outer[i] = pad[i] ^ 0x5c;
  }
  inner.set(msg, 64);
  outer.set(sha1(inner), 64);
  return sha1(outer);
}

async function hmacSha1(keyBytes: Uint8Array, msg: Uint8Array): Promise<Uint8Array> {
  const subtle = typeof crypto !== "undefined" ? crypto.subtle : undefined;
  if (!subtle) return hmacSha1Pure(keyBytes, msg);      // HTTP thường → tự tính
  try {
    const key = await subtle.importKey(
      "raw",
      keyBytes.slice().buffer as ArrayBuffer,
      { name: "HMAC", hash: "SHA-1" },
      false,
      ["sign"],
    );
    const sig = await subtle.sign("HMAC", key, msg.slice().buffer as ArrayBuffer);
    return new Uint8Array(sig);
  } catch {
    return hmacSha1Pure(keyBytes, msg);
  }
}

export async function generateTotpCode(secret: string): Promise<string> {
  const key = base32Decode(secret);
  if (key.length === 0) throw new Error("TOTP secret không hợp lệ (phải là Base32)");
  const hmac = await hmacSha1(key, counterBytes());
  const offset = hmac[hmac.length - 1] & 0x0f;
  const binary =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff);
  return (binary % 1000000).toString().padStart(6, "0");
}

export function totpSecondsRemaining(): number {
  return 30 - (Math.floor(Date.now() / 1000) % 30);
}
