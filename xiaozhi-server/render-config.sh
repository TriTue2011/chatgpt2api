#!/bin/sh
# Sinh .config.yaml của xiaozhi-server từ mẫu + biến môi trường, ghi vào volume
# chung. Chạy một lần bởi service `xiaozhi-config` trước khi xiaozhi-server lên.
set -eu

: "${CHATGPT2API_AUTH_KEY:?can dat CHATGPT2API_AUTH_KEY (giong key cua c2a)}"
: "${SERVER_IP:?can dat SERVER_IP = IP LAN cua host de loa ket noi toi}"

# Dùng '#' làm dấu phân cách sed (key/IP không chứa '#').
sed -e "s#__AUTH_KEY__#${CHATGPT2API_AUTH_KEY}#g" \
    -e "s#__SERVER_IP__#${SERVER_IP}#g" \
    /tpl/data/config.template.yaml > /out/.config.yaml

echo "[xiaozhi-config] da ghi /out/.config.yaml (SERVER_IP=${SERVER_IP})"
