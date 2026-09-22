import assert from "node:assert/strict";
import { test } from "node:test";

import { duongNgheKhiTatMan, moVideoKhiTatMan } from "./nghe-khi-tat-man.ts";

const xem = { coKhungYoutube: true, tiengTrongKhung: true, theoLoa: false };
const xemLoa = { coKhungYoutube: true, tiengTrongKhung: true, theoLoa: true };
const chiNghe = { coKhungYoutube: false, tiengTrongKhung: false, theoLoa: false };

test("iPhone và Safari giữ tiếng trong khung, kể cả khi vừa xem vừa có loa", () => {
  assert.equal(duongNgheKhiTatMan({ webkit: true, ...xem }), "giu-khung");
  assert.equal(duongNgheKhiTatMan({ webkit: true, ...xemLoa }), "giu-khung");
  assert.equal(moVideoKhiTatMan(true), "khung");
});

test("iPhone đang chỉ nghe thì không nạp lại luồng", () => {
  assert.equal(duongNgheKhiTatMan({ webkit: true, ...chiNghe }), "chi-co");
});

test("Chrome và Android xem một mình thì chuyển tiếng, không dựng lại khung", () => {
  assert.equal(duongNgheKhiTatMan({ webkit: false, ...xem }), "chuyen-video");
  assert.equal(moVideoKhiTatMan(false), "the-am");
});

test("Chrome và Android vừa loa vừa máy thì tiếng sang thẻ âm thanh", () => {
  assert.equal(duongNgheKhiTatMan({ webkit: false, ...xemLoa }), "chuyen-loa");
});

test("Chrome đang chỉ nghe thì không đụng luồng", () => {
  assert.equal(duongNgheKhiTatMan({ webkit: false, ...chiNghe }), "chi-co");
});
