// websocket.js — WebSocket real-time handler

let ws = null;
let listeners = [];
let reconnectTimer = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;

export function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const base = window.INGRESS_PATH || '';
    const url = `${protocol}//${location.host}${base}/ws`;

    try {
        ws = new WebSocket(url);
    } catch (e) {
        console.warn('WebSocket connection failed:', e.message);
        scheduleReconnect();
        return;
    }

    ws.onopen = () => {
        console.log('[WS] Connected');
        reconnectAttempts = 0;
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            listeners.forEach(fn => fn(msg));
        } catch (e) { /* ignore non-JSON messages */ }
    };

    ws.onclose = () => {
        console.log('[WS] Disconnected');
        ws = null;
        scheduleReconnect();
    };

    ws.onerror = () => {
        ws?.close();
    };
}

function scheduleReconnect() {
    if (reconnectTimer) return;
    if (reconnectAttempts >= MAX_RECONNECT) return;
    reconnectAttempts++;
    const delay = Math.min(1000 * reconnectAttempts, 30000);
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
    }, delay);
}

export function onMessage(fn) {
    listeners.push(fn);
    return () => { listeners = listeners.filter(f => f !== fn); };
}

export function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}
