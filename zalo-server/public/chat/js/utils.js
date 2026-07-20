// utils.js — helper functions

export function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const now = new Date();
    const h = d.getHours().toString().padStart(2, '0');
    const m = d.getMinutes().toString().padStart(2, '0');
    if (d.toDateString() === now.toDateString()) return `${h}:${m}`;
    const day = d.getDate().toString().padStart(2, '0');
    const month = (d.getMonth() + 1).toString().padStart(2, '0');
    return `${day}/${month} ${h}:${m}`;
}

export function formatDate(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const days = ['Chủ nhật', 'Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7'];
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Hôm nay';
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return 'Hôm qua';
    return `${days[d.getDay()]}, ${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}`;
}

export function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

export function truncate(str, len = 50) {
    if (!str) return '';
    return str.length > len ? str.slice(0, len) + '...' : str;
}

export function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
    return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
}

export function getAvatarColor(name) {
    let hash = 0;
    for (let i = 0; i < (name || '').length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const colors = ['#0068ff', '#ea4335', '#34a853', '#fbbc04', '#ff6d01', '#46bdc6', '#9334e6', '#f538a0'];
    return colors[Math.abs(hash) % colors.length];
}

// ── Emoji rendering ──────────────────────────────────────────────────────

import { convertEmoticons, initEmoticonConverter } from './emojimap.js';

let twemojiReady = false;
let onTwemojiReady = null;

function loadTwemoji() {
    if (typeof twemoji !== 'undefined') { twemojiReady = true; if (onTwemojiReady) onTwemojiReady(); return; }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/@twemoji/api@15.1.0/dist/twemoji.min.js';
    script.integrity = 'sha384-o28+zJO3/45GHIy+9TFKGaYnbt0KQcFRzyBrb0WSSrz7bPGwGI1d64worBiXPgXw';
    script.crossOrigin = 'anonymous';
    script.onload = () => { twemojiReady = true; if (onTwemojiReady) onTwemojiReady(); };
    document.head.appendChild(script);
}

export function initEmoji(onReady) {
    onTwemojiReady = onReady;
    initEmoticonConverter();
    loadTwemoji();
}

export function emojify(html) {
    // Bước 1: convert ASCII emoticon -> unicode emoji (trie từ emoticon-to-emoji)
    let result = convertEmoticons(html);
    // Bước 2: render unicode emoji -> SVG đẹp
    if (twemojiReady && typeof twemoji !== 'undefined') {
        result = twemoji.parse(result, {
            folder: 'svg',
            ext: '.svg',
            base: 'https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/'
        });
    }
    return result;
}
