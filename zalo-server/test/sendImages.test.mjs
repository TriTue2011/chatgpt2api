// Kiểm logic gửi NHIỀU ẢNH (Zalo cá nhân) — chạy: node zalo-server/test/sendImages.test.mjs
//
// Dùng api GIẢ, không gọi Zalo thật: những thứ cần khoá ở đây là quyết định của
// CHÍNH TA (chia lô theo max_file, chặn định dạng trước khi upload, caption chỉ ở
// lô đầu, nghỉ giữa lô), không phải hành vi của Zalo. Gọi Zalo thật trong test là
// đổi một phép đo xác định thành một phép đo phụ thuộc mạng và rate limit — mà
// rate limit của Zalo thì chính người bảo trì zca-js cũng không biết ngưỡng.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const { guiNhieuAnh, docGioiHan, soatDanhSachAnh, taiVeVaGuiNhieuAnh } =
  await import('../utils/sendImages.js');

const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'anh-'));
async function taoAnh(ten, bytes = 1024) {
  const p = path.join(tmp, ten);
  await fs.writeFile(p, Buffer.alloc(bytes, 1));
  return p;
}

function apiGia(maxFile, { thieuSettings = false } = {}) {
  const goi = [];
  return {
    goi,
    getContext: () => thieuSettings ? {} : ({
      settings: { features: { sharefile: {
        max_file: maxFile, max_size_share_file_v3: 1, restricted_ext_file: ['exe'],
      } } },
    }),
    sendMessage: async (content, threadId, type) => {
      goi.push({ so: content.attachments.length, msg: content.msg, threadId, type });
      return { message: content.msg ? { msgId: 'm' } : null,
               attachment: content.attachments.map((_, i) => ({ msgId: 'a' + i })) };
    },
  };
}

let sai = 0;
const kiem = (dieu, ten) => { if (!dieu) { sai++; console.log('  SAI  ' + ten); } else console.log('  ĐÚNG ' + ten); };

// 1. đọc giới hạn thật
kiem(docGioiHan(apiGia(7)).maxFile === 7, 'đọc max_file từ phiên Zalo');
kiem(docGioiHan(apiGia(7, { thieuSettings: true })).maxFile === 6,
     'thiếu settings → dùng chốt an toàn 6, không bắn cả lô');

// 2. chia lô
const anh = [];
for (let i = 0; i < 13; i++) anh.push(await taoAnh(`a${i}.jpg`));
let api = apiGia(5);
let kq = await guiNhieuAnh(api, anh, 'T1', 0, { nghiMs: 1 });
kiem(kq.soLo === 3 && api.goi.map(g => g.so).join(',') === '5,5,3',
     `13 ảnh, max 5 → 3 lô 5+5+3 (thực: ${api.goi.map(g => g.so).join(',')})`);

// 3. caption chỉ ở lô đầu
api = apiGia(5);
await guiNhieuAnh(api, anh, 'T1', 0, { caption: 'chào', nghiMs: 1 });
kiem(api.goi[0].msg === 'chào' && api.goi[1].msg === '' && api.goi[2].msg === '',
     'caption chỉ gắn lô đầu, không lặp mỗi lô');

// 4. cảnh báo nhiều ảnh + chữ
api = apiGia(5);
kq = await guiNhieuAnh(api, anh, 'T1', 0, { caption: 'x', nghiMs: 1 });
kiem(kq.canhBao.some(c => c.includes('TIN RIÊNG')), 'cảnh báo chữ đi tin riêng');

// 5. chặn GIF và ext lạ TRƯỚC khi upload
for (const [ten, mo] of [['x.gif', 'GIF'], ['x.txt', 'ext lạ'], ['x.exe', 'ext Zalo chặn']]) {
  const p = await taoAnh(ten);
  api = apiGia(5);
  let nem = false;
  try { await guiNhieuAnh(api, [p], 'T1', 0, { nghiMs: 1 }); } catch { nem = true; }
  kiem(nem && api.goi.length === 0, `${mo} bị chặn trước khi gửi (không upload gì)`);
}

// 6. ảnh quá lớn (giới hạn 1 MB trong api giả)
const to = await taoAnh('to.jpg', 2 * 1024 * 1024);
api = apiGia(5);
let nem2 = false;
try { await guiNhieuAnh(api, [to], 'T1', 0, { nghiMs: 1 }); } catch { nem2 = true; }
kiem(nem2 && api.goi.length === 0, 'ảnh vượt dung lượng bị chặn sớm');

// 7. msg luôn có (thiếu msg là TypeError trong zca-js)
api = apiGia(5);
await guiNhieuAnh(api, anh.slice(0, 2), 'T1', 0, { nghiMs: 1 });
kiem(api.goi.every(g => typeof g.msg === 'string'), 'msg luôn là chuỗi, không undefined');

// 8. một lô thì không nghỉ
api = apiGia(20);
const t0 = Date.now();
await guiNhieuAnh(api, anh, 'T1', 0, { nghiMs: 400 });
kiem(Date.now() - t0 < 300, 'gửi một lô thì không nghỉ vô ích');

// 9. dọn tệp tạm trên MỌI đường — kể cả khi bị chặn định dạng
// Đây là lý do hàm tải-về nhận saveImage/removeImage từ ngoài: đo được đúng
// việc tệp tạm có bị bỏ lại hay không, mà không phải nạp cả zalo.js.
{
  const daXoa = [];
  const tep = {
    saveImage: async (u) => await taoAnh('tai-' + path.basename(u)),
    removeImage: (p) => daXoa.push(p),
  };

  api = apiGia(5);
  await taiVeVaGuiNhieuAnh(tep, api, ['a.jpg', 'b.jpg'], 'T1', 0, { nghiMs: 1 });
  kiem(daXoa.length === 2, 'gửi xong thì xoá hết tệp tạm');

  daXoa.length = 0;
  api = apiGia(5);
  let nem3 = false;
  try {
    await taiVeVaGuiNhieuAnh(tep, api, ['a.jpg', 'x.gif'], 'T1', 0, { nghiMs: 1 });
  } catch { nem3 = true; }
  kiem(nem3 && daXoa.length === 2 && api.goi.length === 0,
       'bị chặn giữa đường vẫn xoá hết tệp đã tải (không rò đĩa)');

  daXoa.length = 0;
  const tepHong = { ...tep, saveImage: async (u) => (u === 'b.jpg' ? null : await taoAnh('t2.jpg')) };
  let nem4 = false;
  try {
    await taiVeVaGuiNhieuAnh(tepHong, apiGia(5), ['a.jpg', 'b.jpg'], 'T1', 0, { nghiMs: 1 });
  } catch { nem4 = true; }
  kiem(nem4 && daXoa.length === 1, 'tải ảnh thất bại → xoá ảnh đã tải rồi mới báo lỗi');
}

await fs.rm(tmp, { recursive: true, force: true });
console.log(sai ? `\nCÓ ${sai} LỖI` : '\nkhông lỗi');
process.exit(sai ? 1 : 0);
