// components.js — UI rendering

import { formatTime, formatDate, escapeHtml, truncate, getInitials, getAvatarColor, emojify } from './utils.js';

const $ = (sel, ctx = document) => ctx.querySelector(sel);

// ── Account Selector ──────────────────────────────────────────────────────

export function renderAccounts(accounts, onChange) {
    const sel = $('#account-selector');
    sel.innerHTML = '<option value="">-- Chọn tài khoản --</option>' +
        accounts.map(a =>
            `<option value="${a.ownId}">${a.phoneNumber || a.ownId}</option>`
        ).join('');
    sel.onchange = () => onChange(sel.value);
}

// ── Conversation List ─────────────────────────────────────────────────────

export function renderConversations(convs, activeId, onClick) {
    const list = $('#conversation-list');
    const search = $('#search-input')?.value?.toLowerCase() || '';

    const filtered = convs.filter(c =>
        !search || c.name.toLowerCase().includes(search)
    );

    if (filtered.length === 0) {
        list.innerHTML = `<div class="empty-state"><p>${search ? 'Không tìm thấy' : 'Chưa có hội thoại'}</p></div>`;
        return;
    }

    list.innerHTML = filtered.map(c => {
        const active = c.id === activeId ? ' active' : '';
        const initials = getInitials(c.name);
        const color = getAvatarColor(c.name);
        const preview = truncate(c.lastMessage || '', 40);
        const time = c.lastTime ? formatTime(c.lastTime) : '';
        const badge = c.unread ? `<span class="conversation-badge">${c.unread > 99 ? '99+' : c.unread}</span>` : '';
        const typeBadge = c.type === 'group' ? '<span class="conversation-type-badge">Nhóm</span>' : '';

        return `
            <div class="conversation-item${active}" data-id="${c.id}" data-type="${c.type}">
                <div class="conversation-avatar" style="background:${color}20;color:${color}">
                    ${c.avatar ? `<img src="${c.avatar}" alt="">` : initials}
                </div>
                <div class="conversation-body">
                    <div class="conversation-name">${escapeHtml(c.name)}${typeBadge}</div>
                    ${preview ? `<div class="conversation-preview">${escapeHtml(preview)}</div>` : ''}
                </div>
                <div class="conversation-meta">
                    ${time ? `<span class="conversation-time">${time}</span>` : ''}
                    ${badge}
                </div>
            </div>
        `;
    }).join('');

    list.querySelectorAll('.conversation-item').forEach(el => {
        el.addEventListener('click', () => onClick(el.dataset.id, el.dataset.type));
    });
}

// ── Avatar helper ─────────────────────────────────────────────────────────

function renderAvatar(name, avatar, size = 'msg') {
    const initials = getInitials(name);
    const color = getAvatarColor(name);
    if (avatar) {
        return `<img src="${avatar}" alt="" class="avatar-img avatar-${size}" style="background:${color}20">`;
    }
    return `<span class="avatar-text avatar-${size}" style="background:${color}20;color:${color}">${initials}</span>`;
}

// ── Chat Header ───────────────────────────────────────────────────────────

export function renderChatHeader(conv) {
    const initials = getInitials(conv.name);
    const color = getAvatarColor(conv.name);

    $('#chat-avatar').innerHTML = conv.avatar
        ? `<img src="${conv.avatar}" alt="" style="width:100%;height:100%;border-radius:50%;object-fit:cover">`
        : initials;
    $('#chat-avatar').style.background = `${color}20`;
    $('#chat-avatar').style.color = color;

    $('#chat-name').textContent = conv.name;
    $('#chat-subtitle').textContent = conv.type === 'group'
        ? `${conv.memberCount || 0} thành viên`
        : 'Trò chuyện cá nhân';
}

// ── Message List ──────────────────────────────────────────────────────────

let lastDateDivider = '';

function renderBubble(m) {
    if (m.attachment && m.attachment.type === 'photo' && m.attachment.url) {
        let html = `<img src="${m.attachment.url}" alt="Ảnh" class="msg-image" loading="lazy" onclick="window.open(this.src)">`;
        if (m.content && m.content !== '[Ảnh]') {
            html += `<div class="msg-text">${emojify(escapeHtml(m.content))}</div>`;
        }
        return html;
    }
    if (m.attachment && m.attachment.type === 'sticker' && m.attachment.url) {
        return `<img src="${m.attachment.url}" alt="Sticker" class="msg-sticker" loading="lazy">`;
    }
    if (m.attachment && m.attachment.type === 'video' && m.attachment.url) {
        return `<div class="msg-attachment"><span>🎬</span> <a href="${m.attachment.url}" target="_blank">Xem video</a></div>`;
    }
    if (m.attachment && m.attachment.url) {
        return `<div class="msg-attachment"><span>📎</span> <a href="${m.attachment.url}" target="_blank">${escapeHtml(m.content || 'Tệp đính kèm')}</a></div>`;
    }
    return emojify(escapeHtml(m.content || ''));
}

function renderMessageRow(m, conv, ownAvatar) {
    const dateLabel = formatDate(m.ts);
    let divider = '';
    if (dateLabel !== lastDateDivider) {
        lastDateDivider = dateLabel;
        divider = `<div class="message-date-divider"><span>${dateLabel}</span></div>`;
    }
    const side = m.isSelf ? 'sent' : 'received';
    const senderName = m.isSelf ? 'Bạn' : (m.name || 'Unknown');
    const avatar = renderAvatar(senderName, m.isSelf ? (ownAvatar || null) : (m.avatar || conv?.avatar));

    return `${divider}
        <div class="message-row ${side}">
            ${avatar}
            <div class="message-content">
                <div class="message-sender">${escapeHtml(senderName)}</div>
                <div class="message-bubble">${renderBubble(m)}</div>
                <div class="message-time">${formatTime(m.ts)}</div>
            </div>
        </div>`;
}

export function renderMessages(messages, ownId, conv, ownAvatar) {
    const list = $('#message-list');
    if (!messages.length) {
        list.innerHTML = `<div class="empty-state"><div class="empty-icon">💬</div><p>Chưa có tin nhắn</p></div>`;
        return;
    }

    lastDateDivider = '';
    list.innerHTML = messages.map(m => renderMessageRow(m, conv, ownAvatar)).join('');
    scrollToBottom();
}

export function appendMessage(m, ownId, conv, ownAvatar) {
    const list = $('#message-list');
    const html = renderMessageRow(m, conv, ownAvatar);
    list.insertAdjacentHTML('beforeend', html);
    scrollToBottom();
}

function scrollToBottom() {
    const list = $('#message-list');
    requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
}

// ── UI State Helpers ──────────────────────────────────────────────────────

export function showChat(conv) {
    $('#chat-empty').style.display = 'none';
    $('#chat-window').style.display = 'flex';
    renderChatHeader(conv);
    $('#message-list').innerHTML = '<div class="loading-dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
}

export function showEmpty() {
    $('#chat-empty').style.display = 'flex';
    $('#chat-window').style.display = 'none';
}

export function setSidebarEmpty(visible) {
    const el = $('#sidebar-empty');
    if (visible) el.style.display = 'flex';
    else el.style.display = 'none';
}
