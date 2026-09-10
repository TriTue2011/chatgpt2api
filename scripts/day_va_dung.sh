#!/usr/bin/env bash
# Đẩy main → chờ GitHub Actions → HỎNG thì mới dựng ảnh tại chỗ và đẩy lên GHCR.
#
# Chủ máy chốt 10/09/2026: *"Quy trình push main, action lỗi thì build local,
# không lỗi thì thôi. build local dang :latest rồi push image lên github. Tôi
# cần viết cả cái này cho chính bạn và ai claude trên server"* — nên script
# này chạy được ở CẢ HAI nơi:
#
#   máy dev  (macOS, có `gh`)      → đẩy code, hỏi Actions, dựng khi cần
#   máy chủ  (172.16.10.38, không `gh`) → bỏ qua bước hỏi, dựng thẳng
#
# VÌ SAO CẦN NHÁNH DỰNG TẠI CHỖ: đo thật 10/09/2026, ba lần chạy Actions gần
# nhất đều `failure` với cùng một lý do KHÔNG PHẢI LỖI CODE:
#
#   "The job was not started because recent account payments have failed or
#    your spending limit needs to be increased."
#
# Tức hạn mức Actions của tài khoản đã hết. Code vẫn tốt, chỉ là không ai dựng
# ảnh. Không có nhánh này thì mỗi lần đẩy code là một lần phải nhớ vào dựng tay.
#
# SAU KHI ĐẨY ẢNH THÌ KHÔNG PHẢI LÀM GÌ NỮA: watchtower trên máy chủ quét mỗi
# 600 giây và tự kéo bản mới. Đừng thêm bước khởi động lại — hai đường cùng
# làm một việc là cách sinh ra tình huống không ai truy được.
#
#   scripts/day_va_dung.sh                  # đẩy rồi lo trọn vòng
#   scripts/day_va_dung.sh --chi-dung       # bỏ qua đẩy, chỉ dựng và đẩy ảnh
#   scripts/day_va_dung.sh --khong-day-anh  # dựng, gắn :latest, KHÔNG đẩy GHCR
set -uo pipefail

ANH=ghcr.io/tritue2011/chatgpt2api
CHO_TOI_DA=900          # chờ Actions tối đa 15 phút
NHIP_HOI=30

CHI_DUNG=0
DAY_ANH=1
for t in "$@"; do
    case "$t" in
        --chi-dung)      CHI_DUNG=1 ;;
        --khong-day-anh) DAY_ANH=0 ;;
        -h|--help)       sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Tham số lạ: $t" >&2; exit 2 ;;
    esac
done

noi()  { echo "▸ $*"; }
loi()  { echo "✗ $*" >&2; }

GOC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$GOC" || { loi "không vào được $GOC"; exit 1; }

# ── 1. Đẩy code ─────────────────────────────────────────────────────────────
if [ "$CHI_DUNG" -eq 0 ]; then
    NHANH=$(git rev-parse --abbrev-ref HEAD)
    if [ "$NHANH" != "main" ]; then
        loi "đang ở nhánh '$NHANH', không phải main — dừng cho chắc"
        exit 1
    fi
    if [ -n "$(git status --porcelain)" ]; then
        loi "còn thay đổi chưa cam kết — cam kết trước rồi chạy lại"
        git status --short | head -10
        exit 1
    fi
    if [ -z "$(git log --oneline origin/main..HEAD 2>/dev/null)" ]; then
        noi "không có commit mới để đẩy"
    else
        noi "đẩy $(git log --oneline origin/main..HEAD | wc -l | tr -d ' ') commit lên main"
        git push origin main || { loi "đẩy hỏng"; exit 1; }
    fi
fi

SHA=$(git rev-parse --short HEAD)
noi "commit: $SHA"

# ── 2. Hỏi GitHub Actions ───────────────────────────────────────────────────
# Ba kết quả, ba đường đi khác nhau:
#   xong     → Actions đã dựng và đẩy ảnh, mình không phải làm gì
#   hỏng     → dựng tại chỗ (đây là lý do script này tồn tại)
#   khong_ro → không hỏi được (máy chủ không có `gh`) → cũng dựng tại chỗ
#
# `khong_ro` đi cùng đường với `hỏng` là CỐ Ý: dựng thừa một lần chỉ tốn thời
# gian, còn tưởng nhầm là Actions lo rồi thì máy chủ chạy mãi bản cũ mà không
# ai biết — hỏng im lặng, đúng loại lỗi tốn nhiều công nhất để tìm ra.
hoi_actions() {
    command -v gh >/dev/null 2>&1 || { echo khong_ro; return; }
    gh auth status >/dev/null 2>&1 || { echo khong_ro; return; }

    local het=$((SECONDS + CHO_TOI_DA)) js tt kl
    while [ $SECONDS -lt $het ]; do
        js=$(gh run list --workflow="Publish Docker Image" --limit 1 \
                --json headSha,status,conclusion 2>/dev/null) || { echo khong_ro; return; }
        tt=$(printf '%s' "$js" | python3 -c \
            'import json,sys
try: r=json.load(sys.stdin)[0]
except Exception: print("");raise SystemExit
print(r.get("status") or "")' 2>/dev/null)
        kl=$(printf '%s' "$js" | python3 -c \
            'import json,sys
try: r=json.load(sys.stdin)[0]
except Exception: print("");raise SystemExit
print(r.get("conclusion") or "")' 2>/dev/null)
        [ -z "$tt" ] && { echo khong_ro; return; }
        if [ "$tt" = "completed" ]; then
            [ "$kl" = "success" ] && { echo xong; return; }
            echo hong; return
        fi
        noi "Actions đang chạy ($tt)… chờ ${NHIP_HOI}s"
        sleep "$NHIP_HOI"
    done
    noi "chờ quá ${CHO_TOI_DA}s mà Actions chưa xong"
    echo hong
}

KQ=$(hoi_actions)
case "$KQ" in
    xong)
        noi "Actions đã dựng và đẩy ảnh — không cần làm gì thêm."
        noi "watchtower sẽ kéo về trong ≤10 phút."
        exit 0 ;;
    hong)     noi "Actions KHÔNG dựng được → dựng tại chỗ" ;;
    khong_ro) noi "không hỏi được Actions (thiếu gh) → dựng tại chỗ" ;;
esac

# ── 3. Dựng tại chỗ ─────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || { loi "máy này không có docker"; exit 1; }

# Gắn HAI thẻ trong CÙNG một lần dựng: `local-<sha>` để còn lùi lại được, và
# `:latest` là thứ máy chủ đang chạy. Dựng xong mới gắn thẻ ở lệnh riêng thì
# có lúc `:latest` trỏ vào ảnh cũ vì thẻ chạy trước khi dựng xong — đã mắc
# 10/09/2026.
noi "dựng $ANH:local-$SHA và :latest (có thể mất vài chục phút)"
if ! docker build -f Dockerfile -t "$ANH:local-$SHA" -t "$ANH:latest" .; then
    loi "dựng ảnh hỏng"
    exit 1
fi
noi "dựng xong"

if [ "$DAY_ANH" -eq 0 ]; then
    noi "bỏ qua đẩy ảnh (--khong-day-anh). Ảnh đã có tại chỗ."
    exit 0
fi

# ── 4. Đẩy ảnh lên GHCR ─────────────────────────────────────────────────────
if ! docker push "$ANH:local-$SHA"; then
    loi "đẩy ảnh hỏng — kiểm tra đăng nhập: docker login ghcr.io"
    exit 1
fi
docker push "$ANH:latest" || { loi "đẩy :latest hỏng"; exit 1; }

# ── 5. Dọn ảnh cũ ───────────────────────────────────────────────────────────
# Mỗi ảnh 5,76 GB nên không dọn là đầy đĩa rất nhanh.
#
# GIỮ LẠI `_GIU_LAI` bản gần nhất, KHÔNG dọn sạch: chủ máy đã gặp chuyện cron
# 0h00 chạy `docker image prune -a -f` xoá cả bản dự phòng, và khi bản mới
# hỏng thì không còn gì để lùi về. Dọn là để khỏi đầy đĩa, không phải để trống
# đĩa.
#
# Chỉ đụng thẻ `local-*` do script này tạo. Ảnh của Actions, ảnh dịch vụ khác,
# và `:latest` không nằm trong diện dọn.
_GIU_LAI=3
noi "dọn ảnh local-* cũ, giữ $_GIU_LAI bản gần nhất"
CU=$(docker images "$ANH" --format '{{.Tag}}\t{{.CreatedAt}}' \
     | grep -E '^local-' | sort -k2 -r | tail -n "+$((_GIU_LAI + 1))" | cut -f1)
if [ -z "$CU" ]; then
    noi "chưa có bản nào quá cũ"
else
    for t in $CU; do
        # `:latest` và ảnh đang chạy trỏ cùng một ID với một trong các thẻ này,
        # nên `docker rmi` chỉ gỡ THẺ chứ không xoá mất ảnh đang dùng — Docker
        # tự từ chối xoá lớp còn container tham chiếu.
        docker rmi "$ANH:$t" >/dev/null 2>&1 && noi "  bỏ thẻ $t" || true
    done
fi
docker image prune -f >/dev/null 2>&1 || true   # chỉ lớp mồ côi, KHÔNG dùng -a
noi "đĩa còn trống: $(df -h / | awk 'NR==2{print $4}')"

noi "xong. $ANH:latest = $SHA"
noi "watchtower quét mỗi 600s và tự kéo về — không cần khởi động lại tay."
