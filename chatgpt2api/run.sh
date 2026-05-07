#!/bin/bash
set -e

PORT=80

if [ "$HA_ADDON" = "true" ]; then
    echo "[Info] Khởi động trong chế độ Home Assistant Add-on..."
    
    # Đọc cấu hình từ Home Assistant Options
    if [ -f /data/options.json ]; then
        AUTH_KEY=$(jq --raw-output '.auth_key // empty' /data/options.json)
        BASE_URL=$(jq --raw-output '.base_url // empty' /data/options.json)
        PROXY=$(jq --raw-output '.proxy // empty' /data/options.json)
        
        if [ -n "$AUTH_KEY" ]; then
            export CHATGPT2API_AUTH_KEY="$AUTH_KEY"
            echo "[Info] Đã nạp auth_key từ cấu hình Add-on."
        fi
        if [ -n "$BASE_URL" ]; then
            export CHATGPT2API_BASE_URL="$BASE_URL"
            echo "[Info] Đã nạp base_url từ cấu hình Add-on."
        fi
        if [ -n "$PROXY" ]; then
            export HTTP_PROXY="$PROXY"
            export HTTPS_PROXY="$PROXY"
            export ALL_PROXY="$PROXY"
            echo "[Info] Đã nạp proxy từ cấu hình Add-on."
        fi
    fi

    mkdir -p /data/app_data
    
    # Symlink thư mục data để dữ liệu không bị xóa khi khởi động lại
    if [ ! -L /app/data ]; then
        echo "[Info] Thiết lập liên kết dữ liệu cố định (Persistent Data)..."
        cp -rn /app/data/* /data/app_data/ 2>/dev/null || true
        rm -rf /app/data
        ln -s /data/app_data /app/data
    fi

    # Symlink config.json
    if [ ! -f /data/config.json ]; then
        if [ -f /app/config.json ]; then
            cp /app/config.json /data/config.json
        else
            echo "{}" > /data/config.json
        fi
    fi
    if [ ! -L /app/config.json ]; then
        rm -f /app/config.json
        ln -s /data/config.json /app/config.json
    fi
else
    echo "[Info] Khởi động trong chế độ Docker độc lập..."
fi

echo "[Info] Đang khởi chạy ChatGPT2API tại cổng $PORT"
exec uv run uvicorn main:app --host 0.0.0.0 --port $PORT --access-log
