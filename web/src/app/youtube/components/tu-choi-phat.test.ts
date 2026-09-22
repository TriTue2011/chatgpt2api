import assert from "node:assert/strict";
import { test } from "node:test";

import { cachXuLyTuChoi } from "./tu-choi-phat.ts";

test("AbortError là lần phát bị cắt, không báo", () => {
  assert.equal(cachXuLyTuChoi("AbortError", false, false), "bo");
  assert.equal(cachXuLyTuChoi("AbortError", true, true), "bo");
});

test("NotSupportedError lúc chưa có lỗi trên phần tử thì thử lại một lần", () => {
  assert.equal(cachXuLyTuChoi("NotSupportedError", false, false), "lai");
  assert.equal(cachXuLyTuChoi("NotSupportedError", false, true), "bo");
});

test("NotSupportedError khi phần tử đã có lỗi không tự kết luận — sự kiện error kết luận", () => {
  assert.equal(cachXuLyTuChoi("NotSupportedError", true, false), "bo");
});

test("NotAllowedError và lỗi khác báo ngay", () => {
  assert.equal(cachXuLyTuChoi("NotAllowedError", false, false), "bao");
  assert.equal(cachXuLyTuChoi("Error", false, false), "bao");
});
