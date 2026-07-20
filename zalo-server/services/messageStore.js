// messageStore.js — File-based message persistence
import fs from 'fs';
import path from 'path';
import { getDataDirectory } from '../config/addon.js';

const MAX_MESSAGES = 1000;

function getStoreDir() {
    const dir = path.join(getDataDirectory(), 'messages');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    return dir;
}

function getAccountDir(ownId) {
    const dir = path.join(getStoreDir(), ownId);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    return dir;
}

function getThreadFile(ownId, threadId) {
    return path.join(getAccountDir(ownId), `${threadId}.json`);
}

export function loadMessages(ownId, threadId) {
    try {
        const file = getThreadFile(ownId, threadId);
        if (!fs.existsSync(file)) return [];
        const raw = fs.readFileSync(file, 'utf-8');
        return JSON.parse(raw);
    } catch (e) {
        console.warn(`[MsgStore] Lỗi đọc ${ownId}/${threadId}:`, e.message);
        return [];
    }
}

export function saveMessage(ownId, threadId, msg) {
    try {
        const file = getThreadFile(ownId, threadId);
        let messages = [];
        if (fs.existsSync(file)) {
            try { messages = JSON.parse(fs.readFileSync(file, 'utf-8')); } catch (e) { /* reset nếu corrupt */ }
        }
        // Tránh duplicate
        if (messages.some(m => m.id === msg.id)) return;
        messages.push(msg);
        if (messages.length > MAX_MESSAGES) messages = messages.slice(-MAX_MESSAGES);
        fs.writeFileSync(file, JSON.stringify(messages, null, 2), 'utf-8');
    } catch (e) {
        console.warn(`[MsgStore] Lỗi ghi ${ownId}/${threadId}:`, e.message);
    }
}

export function getLastMessageTime(ownId, threadId) {
    const messages = loadMessages(ownId, threadId);
    if (!messages.length) return 0;
    return messages[messages.length - 1].ts || 0;
}
