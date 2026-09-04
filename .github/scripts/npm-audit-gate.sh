#!/usr/bin/env bash
# Cổng npm audit CHỊU ĐƯỢC lúc endpoint npm chết.
#
# `npm audit` exit != 0 cho CẢ "có lỗ hổng" LẪN "không gọi được endpoint". Cổng
# cũ (`npm audit … || exit 1`) gán nhầm endpoint-chết thành "phát hiện lỗ hổng"
# rồi đỏ CI và dán nhãn sai — đo 04/09: npm trả 503 Service Unavailable,
# workflow báo "npm audit high/critical findings" trong khi KHÔNG có lỗ hổng nào.
#
# Ở đây đọc `--json`: chỉ CHẶN khi ĐẾM ĐƯỢC lỗ hổng thật ở mức yêu cầu; endpoint
# lỗi thì cảnh báo và cho qua (bảo mật vẫn được rà lại ở lần chạy sau).
#
# Dùng: npm-audit-gate.sh <high|critical>   (chạy trong thư mục có package.json)
set -uo pipefail
LEVEL="${1:-critical}"
OUT="$(npm audit --omit=dev --omit=optional --json 2>/dev/null || true)"
COUNT="$(printf '%s' "$OUT" | node -e '
let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  let j; try { j = JSON.parse(s) } catch (e) { return process.stdout.write("ERR") }
  const v = j && j.metadata && j.metadata.vulnerabilities;
  if ((j && j.error) || !v) return process.stdout.write("ERR");
  const lvl = process.argv[1];
  const n = (v.critical || 0) + (lvl === "high" ? (v.high || 0) : 0);
  process.stdout.write(String(n));
});' "$LEVEL")"
if [ "$COUNT" = "ERR" ]; then
  echo "::warning::npm audit không gọi được endpoint (KHÔNG phải lỗ hổng) — bỏ qua cổng lần này"
  exit 0
fi
if [ "$COUNT" -gt 0 ]; then
  echo "::error::npm audit tìm thấy $COUNT lỗ hổng mức >= $LEVEL"
  npm audit --omit=dev --omit=optional --audit-level="$LEVEL" || true
  exit 1
fi
echo "npm audit ($LEVEL): sạch (0 lỗ hổng >= $LEVEL)"
