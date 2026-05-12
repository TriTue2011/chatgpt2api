#!/usr/bin/with-contenv bashio

# chatgpt2api - Home Assistant Addon
# =====================================

CONFIG_PATH=/data/options.json
AUTH_KEY=$(bashio::config 'auth_key')

export CHATGPT2API_AUTH_KEY="${AUTH_KEY}"

# Start chatgpt2api
cd /app
exec uv run uvicorn main:app --host 0.0.0.0 --port 3030
