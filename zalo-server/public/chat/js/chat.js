// chat.js — Main application entry point

import * as API from './api.js';
import { connect, onMessage } from './websocket.js';
import {
    renderAccounts, renderConversations, renderMessages,
    appendMessage, showChat, showEmpty, setSidebarEmpty
} from './components.js';
import { initEmoji } from './utils.js';

// ── State ─────────────────────────────────────────────────────────────────

const state = {
    accounts: [],
    currentAccount: null,
    conversations: [],
    activeConv: null,
    messages: [],
    ownAvatar: null
};

// ── Helpers ───────────────────────────────────────────────────────────────

function sortConversations() {
    state.conversations.sort((a, b) => b.lastTime - a.lastTime);
}

function refreshConversationList(activeId) {
    sortConversations();
    renderConversations(state.conversations, activeId, openConversation);
}

// ── Init ──────────────────────────────────────────────────────────────────

async function init() {
    setupTheme();
    initEmoji(() => {
        // Re-render sau khi twemoji load xong
        if (state.messages.length) {
            renderMessages(state.messages, state.currentAccount, state.activeConv, state.ownAvatar);
        }
    });
    connect();

    onMessage(handleIncomingMessage);

    try {
        state.accounts = await API.fetchAccounts();
        renderAccounts(state.accounts, onAccountChange);
        if (state.accounts.length > 0) {
            $('#account-selector').value = state.accounts[0].ownId;
            await onAccountChange(state.accounts[0].ownId);
        }
    } catch (e) {
        console.error('Khởi tạo thất bại:', e);
        if (e.message.includes('401') || e.message.includes('đăng nhập')) {
            // PWA standalone: mở login trong browser ngoài
            if (window.matchMedia('(display-mode: standalone)').matches) {
                window.open((window.INGRESS_PATH || '') + '/admin-login', '_blank');
            } else {
                window.location.href = (window.INGRESS_PATH || '') + '/admin-login';
            }
        }
    }

    $('#search-input').addEventListener('input', () => {
        renderConversations(state.conversations, state.activeConv?.id, openConversation);
    });

    $('#message-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendCurrentMessage();
        }
    });

    $('#send-btn').addEventListener('click', sendCurrentMessage);

    // Mobile: nút back
    $('#back-btn').addEventListener('click', goBackToSidebar);
}

// ── Mobile navigation ────────────────────────────────────────────────────

function isMobile() { return window.innerWidth <= 768; }

function goBackToSidebar() {
    state.activeConv = null;
    state.messages = [];
    showEmpty();
    if (isMobile()) {
        document.getElementById('sidebar').classList.remove('sidebar-hidden');
    }
}

function openConversation(id, type) {
    if (isMobile()) {
        document.getElementById('sidebar').classList.add('sidebar-hidden');
    }
    onConversationClick(id, type);
}

// ── Account ───────────────────────────────────────────────────────────────

async function onAccountChange(ownId) {
    if (!ownId) return;
    state.currentAccount = ownId;
    state.activeConv = null;
    state.messages = [];
    showEmpty();
    setSidebarEmpty(false);

    try {
        const result = await API.fetchConversations(ownId);
        state.conversations = result.data || [];
        state.ownAvatar = result.ownAvatar || null;
        setSidebarEmpty(state.conversations.length === 0);
        sortConversations();
        renderConversations(state.conversations, null, openConversation);
    } catch (e) {
        console.error('Lỗi tải hội thoại:', e);
    }
}

// ── Conversation ──────────────────────────────────────────────────────────

async function onConversationClick(id, type) {
    if (!state.currentAccount) return;

    const conv = state.conversations.find(c => c.id === id);
    if (!conv) return;

    // Reset unread count
    conv.unread = 0;

    state.activeConv = { ...conv, type };
    showChat(state.activeConv);

    try {
        const result = await API.fetchMessages(state.currentAccount, id, type);
        state.messages = result.data || [];
        state.ownAvatar = result.ownAvatar || state.ownAvatar;
        renderMessages(state.messages, state.currentAccount, state.activeConv, state.ownAvatar);
    } catch (e) {
        console.error('Lỗi tải tin nhắn:', e);
        $('#message-list').innerHTML = '<div class="empty-state"><p>Không thể tải lịch sử chat</p></div>';
    }

    refreshConversationList(id);
}

// ── Send ──────────────────────────────────────────────────────────────────

async function sendCurrentMessage() {
    const input = $('#message-input');
    const text = input.value.trim();
    if (!text || !state.activeConv || !state.currentAccount) return;

    const { id, type } = state.activeConv;
    input.value = '';
    input.style.height = 'auto';

    try {
        const result = await API.sendMessage(state.currentAccount, id, text, type);
        const realId = String(result?.data?.message?.msgId || result?.data?.msgId || ('sent_' + Date.now()));
        const msg = {
            id: realId,
            from: state.currentAccount,
            name: 'Bạn',
            content: text,
            ts: Date.now(),
            isSelf: true
        };
        // Chỉ append nếu WebSocket chưa kịp echo
        if (!state.messages.some(m => m.id === msg.id)) {
            state.messages.push(msg);
            appendMessage(msg, state.currentAccount, state.activeConv, state.ownAvatar);
        }

        const conv = state.conversations.find(c => c.id === id);
        if (conv) {
            conv.lastMessage = text;
            conv.lastTime = Date.now();
        }
        refreshConversationList(id);
    } catch (e) {
        console.error('Lỗi gửi tin nhắn:', e);
    }
}

// ── Incoming Messages ─────────────────────────────────────────────────────

function handleIncomingMessage(msg) {
    if (!state.currentAccount) {
        console.log('[WS] Bỏ qua msg vì chưa chọn tài khoản');
        return;
    }

    const accountId = msg._accountId;
    if (accountId && accountId !== state.currentAccount) {
        console.log('[WS] Bỏ qua msg vì khác account:', accountId, 'vs', state.currentAccount);
        return;
    }

    const threadId = msg.threadId || msg.data?.idTo;
    const { text, attachment } = extractMsgContent(msg);

    if (!text && !attachment) return;

    const isSelf = msg.isSelf || msg.data?.uidFrom === state.currentAccount;

    const m = {
        id: msg.data?.msgId || ('ws_' + Date.now()),
        from: msg.data?.uidFrom,
        name: msg.data?.dName || 'Unknown',
        avatar: msg.data?._avatar || null,
        content: text,
        attachment: attachment || undefined,
        ts: Number(msg.data?.ts || 0),
        isSelf
    };

    console.log('[WS] Tin nhắn mới:', m.name, '-', text || attachment?.type, '| threadId:', threadId, '| active:', state.activeConv?.id);

    if (state.activeConv && threadId === state.activeConv.id) {
        if (!state.messages.some(x => x.id === m.id)) {
            state.messages.push(m);
            appendMessage(m, state.currentAccount, state.activeConv, state.ownAvatar);
        }
    }

    const conv = state.conversations.find(c => c.id === threadId);
    if (conv) {
        conv.lastMessage = (isSelf ? 'Bạn: ' : '') + (text || '[Ảnh]');
        conv.lastTime = m.ts;
        if (!state.activeConv || threadId !== state.activeConv.id) {
            conv.unread = (conv.unread || 0) + 1;
        }
    } else if (threadId && threadId !== state.currentAccount) {
        console.log('[WS] Thêm hội thoại mới:', msg.data?.dName, threadId);
        state.conversations.unshift({
            id: threadId,
            name: msg.data?.dName || threadId,
            type: msg.type === 1 ? 'group' : 'user',
            lastMessage: text || '[Ảnh]',
            lastTime: m.ts,
            unread: 1
        });
    }

    refreshConversationList(state.activeConv?.id);
}

// Trích xuất nội dung từ mọi loại tin nhắn
function extractMsgContent(msg) {
    const c = msg.data?.content;
    if (!c) return { text: '', attachment: null };
    if (typeof c === 'string') return { text: c, attachment: null };
    if (msg.data?.msgType === 'chat.photo' && c.href) {
        return { text: '[Ảnh]', attachment: { type: 'photo', url: c.href, thumb: c.thumb } };
    }
    if (msg.data?.msgType === 'chat.sticker') {
        return { text: '[Sticker]', attachment: { type: 'sticker', url: c.href } };
    }
    if (msg.data?.msgType === 'chat.video' && c.href) {
        return { text: '[Video]', attachment: { type: 'video', url: c.href, thumb: c.thumb } };
    }
    if (c.href) {
        return { text: c.title || c.description || '[File]', attachment: { type: 'file', url: c.href } };
    }
    if (c.msg) return { text: c.msg, attachment: null };
    return { text: c.title || '', attachment: null };
}

// ── Theme ─────────────────────────────────────────────────────────────────

function setupTheme() {
    const stored = localStorage.getItem('chat-theme');
    if (stored) {
        document.documentElement.setAttribute('data-theme', stored);
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }

    const btn = document.getElementById('theme-toggle');
    updateThemeIcon();
    btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('chat-theme', next);
        updateThemeIcon();
    });
}

function updateThemeIcon() {
    const btn = document.getElementById('theme-toggle');
    const theme = document.documentElement.getAttribute('data-theme');
    btn.textContent = theme === 'dark' ? '☀️' : '🌙';
}

// ── DOM helpers ───────────────────────────────────────────────────────────

function $(sel) { return document.querySelector(sel); }

// ── Start ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
