import { ThreadType } from "zca-js";
import { getWebhookUrl, triggerN8nWebhook, getCookiesDir } from './utils/helpers.js';
import { broadcastToWebsocket } from './services/webhookService.js';
import { saveMessage } from './services/messageStore.js';
import fs from 'fs';
import path from 'path';
import { broadcastMessage } from './services/websocketHub.js';
import { enrichMessageEvent } from './utils/zaloContract.js';
import { reconnectDelay } from './services/reconnectPolicy.js';
import {
    beginReconnectAttempt,
    invalidateReconnectAttempt,
} from './services/reconnectGuard.js';
import { storeGroupMessage } from './utils/groupHistoryStore.js';
import { withTimeout } from './utils/timeout.js';

let reconnectLogin = null;
let accountRegistry = [];

export function configureReconnectDependencies({ login, accounts }) {
    if (typeof login !== 'function' || !Array.isArray(accounts)) {
        throw new Error('Reconnect dependencies khong hop le');
    }
    reconnectLogin = login;
    accountRegistry = accounts;
}

export const reloginAttempts = new Map();
const reconnectStates = new Map();

function reconnectTimeoutMs() {
    const timeout = Number.parseInt(process.env.RECONNECT_LOGIN_TIMEOUT_MS || '60000', 10);
    return Number.isSafeInteger(timeout) && timeout > 0 ? timeout : 60000;
}

function clearReconnectState(ownId) {
    const state = reconnectStates.get(ownId);
    if (state?.timer) clearTimeout(state.timer);
    reconnectStates.delete(ownId);
    reloginAttempts.delete(ownId);
}

function scheduleRelogin(api) {
    const ownId = api?.getOwnId?.();
    if (!ownId) return;
    const current = accountRegistry.find((account) => String(account.ownId) === String(ownId));
    if (current?.api && current.api !== api) return;

    let state = reconnectStates.get(ownId);
    if (!state) {
        state = {
            attempt: 0, timer: null, running: false, sourceApi: api, generation: 0,
        };
        reconnectStates.set(ownId, state);
    }
    if (state.running || state.timer) return;

    const delay = reconnectDelay(state.attempt);
    console.log(`[Reconnect] Thu lai ${ownId} sau ${Math.round(delay / 1000)}s (lan ${state.attempt + 1}).`);
    state.timer = setTimeout(() => { void attemptRelogin(ownId); }, delay);
    state.timer.unref?.();
}

async function attemptRelogin(ownId) {
    const state = reconnectStates.get(ownId);
    if (!state || state.running) return;
    state.timer = null;
    state.running = true;
    const isCurrentAttempt = beginReconnectAttempt(reconnectStates, ownId, state);
    reloginAttempts.set(ownId, Date.now());

    try {
        const account = accountRegistry.find((item) => String(item.ownId) === String(ownId));
        if (account?.api && account.api !== state.sourceApi) {
            clearReconnectState(ownId);
            return;
        }

        const credentialPath = path.join(getCookiesDir(), `cred_${ownId}.json`);
        if (!fs.existsSync(credentialPath)) {
            console.error(`[Reconnect] Khong co credential cho ${ownId}.`);
            clearReconnectState(ownId);
            return;
        }
        const credential = JSON.parse(fs.readFileSync(credentialPath, 'utf8'));
        const hasSavedProxy = Object.prototype.hasOwnProperty.call(credential, 'proxy');
        const hasAccountProxy = account
            && Object.prototype.hasOwnProperty.call(account, 'proxy');
        const savedProxy = hasSavedProxy ? (credential.proxy || null) : (account?.proxy || null);

        if (!reconnectLogin) throw new Error('Reconnect chua duoc khoi tao');
        await withTimeout(
            reconnectLogin(savedProxy, credential, {
                allowQrFallback: false,
                autoSelectProxy: !(hasSavedProxy || hasAccountProxy),
                isCurrentAttempt,
            }),
            reconnectTimeoutMs(),
            'Reconnect login timeout',
        );
        clearReconnectState(ownId);
    } catch (error) {
        console.error(`[Reconnect] Lan ${state.attempt + 1} loi cho ${ownId}: ${error.message}`);
        // Login da timeout co the van dang chay trong SDK. Danh dau no la cu
        // truoc khi dat retry de no khong duoc phep commit khi ket thuc muon.
        invalidateReconnectAttempt(state);
        state.running = false;
        state.attempt += 1;
        reconnectStates.set(ownId, state);
        // Khong xoa cookie, khong mo QR ngam; tiep tuc den tran 5 phut.
        scheduleRelogin(state.sourceApi);
    }
}

// Trích xuất nội dung hiển thị từ mọi loại tin nhắn
function extractMessageContent(msg) {
    const c = msg.data?.content;
    if (!c) return { text: '', attachment: null };
    // Text thuần
    if (typeof c === 'string') return { text: c, attachment: null };
    // Ảnh
    if (msg.data?.msgType === 'chat.photo' && c.href) {
        return { text: '[Ảnh]', attachment: { type: 'photo', url: c.href, thumb: c.thumb } };
    }
    // Sticker
    if (msg.data?.msgType === 'chat.sticker') {
        return { text: '[Sticker]', attachment: { type: 'sticker', url: c.href } };
    }
    // Video
    if (msg.data?.msgType === 'chat.video' && c.href) {
        return { text: '[Video]', attachment: { type: 'video', url: c.href, thumb: c.thumb } };
    }
    // File / link khác
    if (c.href) {
        return { text: c.title || c.description || '[File]', attachment: { type: 'file', url: c.href } };
    }
    // Object có msg field
    if (c.msg) return { text: c.msg, attachment: null };
    return { text: c.title || '', attachment: null };
}

export function setupEventListeners(api, loginResolve) {
    const ownId = api.getOwnId();
    
    // Lắng nghe sự kiện tin nhắn và gửi đến webhook được cấu hình cho tin nhắn
    api.listener.on("message", (msg) => {
        if (Number(msg?.type) === ThreadType.Group) {
            storeGroupMessage(ownId, msg);
        }
        const messageWebhookUrl = getWebhookUrl("messageWebhookUrl", ownId);
        const msgWithOwnId = enrichMessageEvent(msg, ownId);

        if (messageWebhookUrl) {
            triggerN8nWebhook(msgWithOwnId, messageWebhookUrl);
        }

        broadcastToWebsocket(msgWithOwnId);

        // Lưu vào message store để có lịch sử chat cá nhân (cả tin nhận lẫn tin tự gửi từ app)
        try {
            if (!msg.isSelf && msg.type === ThreadType.User) {
                const threadId = msg.threadId || msg.data?.idTo;
                const { text, attachment } = extractMessageContent(msg);
                if (threadId && (text || attachment)) {
                    saveMessage(ownId, threadId, {
                        id: msg.data?.msgId || ('ws_' + Date.now()),
                        from: msg.data?.uidFrom,
                        name: msg.data?.dName || 'Unknown',
                        content: text,
                        attachment: attachment || undefined,
                        ts: Number(msg.data?.ts || 0),
                        isSelf: false
                    });
                }
            }
        } catch (e) {
            console.warn('[Event] Lỗi lưu tin nhắn:', e.message);
        }
    });

    // Lắng nghe sự kiện nhóm và gửi đến webhook được cấu hình cho sự kiện nhóm
    api.listener.on("group_event", (data) => {
        const groupEventWebhookUrl = getWebhookUrl("groupEventWebhookUrl", ownId);
        // Thêm ownId vào dữ liệu
        const dataWithOwnId = { ...data, _accountId: ownId };
        
        // Gửi tới webhook nếu được cấu hình
        if (groupEventWebhookUrl) {
            triggerN8nWebhook(dataWithOwnId, groupEventWebhookUrl);
        }
        
        // Broadcast sự kiện nhóm tới WebSocket 
        broadcastToWebsocket(dataWithOwnId);
    });

    // Lắng nghe sự kiện reaction và gửi đến webhook được cấu hình cho reaction
    api.listener.on("reaction", (reaction) => {
        const reactionWebhookUrl = getWebhookUrl("reactionWebhookUrl", ownId);
        console.log("Nhận reaction:", reaction);
        if (reactionWebhookUrl) {
            // Thêm ownId vào dữ liệu
            const reactionWithOwnId = { ...reaction, _accountId: ownId };
            triggerN8nWebhook(reactionWithOwnId, reactionWebhookUrl);
        }
    });

    api.listener.onConnected(() => {
        clearReconnectState(ownId);
        // Gửi thông báo đến tất cả client
        try {
            broadcastMessage('login_success');
        } catch (err) {
            console.error('Lỗi khi gửi thông báo WebSocket:', err);
        }
    });
    
    api.listener.onClosed(() => {
        console.log(`Closed - API listener đã ngắt kết nối cho tài khoản ${ownId}`);
        
        scheduleRelogin(api);
    });
    
    api.listener.onError((error) => {
        console.error(`Error on account ${ownId}:`, error);
    });
}
