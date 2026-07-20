import express from 'express';
import fs from 'fs';
import path from 'path';
import { zaloAccounts } from '../api/zalo/zalo.js';
import { ThreadType } from 'zca-js';
import { loadMessages, saveMessage } from '../services/messageStore.js';
import { getDataDirectory } from '../config/addon.js';

const router = express.Router();

function getAccount(selection) {
    if (!selection) throw new Error('Vui lòng chọn tài khoản');
    let acc = zaloAccounts.find(a => a.ownId === selection);
    if (!acc) acc = zaloAccounts.find(a => a.phoneNumber === selection);
    if (!acc) throw new Error(`Không tìm thấy tài khoản: ${selection}`);
    return acc;
}

// ── Lấy danh sách hội thoại (groups + friends) ────────────────────────────
router.post('/conversations', async (req, res) => {
    try {
        const { accountSelection } = req.body;
        const account = getAccount(accountSelection);
        const ownId = account.ownId;
        const conversations = [];

        // Lấy avatar của chính mình
        let ownAvatar = null;
        try {
            const ownInfo = await account.api.getUserInfo([ownId]);
            const ownProfile = ownInfo?.changed_profiles?.[`${ownId}_0`] || ownInfo?.changed_profiles?.[ownId];
            ownAvatar = ownProfile?.avatar || null;
        } catch (e) { /* không crash */ }

        // Nhóm: dùng API, không cần store
        try {
            const groupsData = await account.api.getAllGroups();
            if (groupsData && groupsData.gridVerMap) {
                const groupIds = Object.keys(groupsData.gridVerMap);
                if (groupIds.length > 0) {
                    const info = await account.api.getGroupInfo(groupIds);
                    if (info && info.gridInfoMap) {
                        for (const [id, g] of Object.entries(info.gridInfoMap)) {
                            conversations.push({
                                id,
                                name: g.name || 'Nhóm không tên',
                                avatar: g.avt || g.fullAvt || null,
                                type: 'group',
                                memberCount: g.totalMember || 0,
                                lastMessage: '',
                                lastTime: 0
                            });
                        }
                    }
                }
            }
        } catch (e) {
            console.warn('Lỗi lấy danh sách nhóm:', e.message);
        }

        // Bạn bè: load lastMessage từ store
        try {
            const friends = await account.api.getAllFriends();
            if (Array.isArray(friends)) {
                for (const f of friends) {
                    const stored = loadMessages(ownId, f.userId);
                    const lastMsg = stored.length ? stored[stored.length - 1] : null;
                    conversations.push({
                        id: f.userId,
                        name: f.displayName || f.zaloName || f.userId,
                        avatar: f.avatar || null,
                        type: 'user',
                        lastMessage: lastMsg ? lastMsg.content : '',
                        lastTime: lastMsg ? lastMsg.ts : 0
                    });
                }
            }
        } catch (e) {
            console.warn('Lỗi lấy danh sách bạn bè:', e.message);
        }

        // Người lạ (không trong friends) — load từ message store
        try {
            const storeDir = path.join(getDataDirectory(), 'messages', ownId);
            if (fs.existsSync(storeDir)) {
                const files = fs.readdirSync(storeDir);
                for (const file of files) {
                    if (!file.endsWith('.json')) continue;
                    const threadId = file.replace('.json', '');
                    if (conversations.some(c => c.id === threadId)) continue;
                    const stored = loadMessages(ownId, threadId);
                    if (!stored.length) continue;
                    const lastMsg = stored[stored.length - 1];
                    conversations.push({
                        id: threadId,
                        name: lastMsg.name || threadId,
                        avatar: lastMsg.avatar || null,
                        type: 'user',
                        lastMessage: lastMsg.content || '',
                        lastTime: lastMsg.ts || 0
                    });
                }
            }
        } catch (e) {
            console.warn('Lỗi scan message store:', e.message);
        }

        conversations.sort((a, b) => b.lastTime - a.lastTime);

        res.json({
            success: true,
            data: conversations,
            ownAvatar,
            usedAccount: { ownId, phoneNumber: account.phoneNumber }
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// ── Lấy lịch sử chat ─────────────────────────────────────────────────────
router.post('/messages', async (req, res) => {
    try {
        const { threadId, type, count, accountSelection } = req.body;
        if (!threadId) return res.status(400).json({ error: 'threadId là bắt buộc' });

        const account = getAccount(accountSelection);
        const ownId = account.ownId;
        let messages = [];

        // Lấy avatar của chính mình
        let ownAvatar = null;
        try {
            const ownInfo = await account.api.getUserInfo([ownId]);
            const ownProfile = ownInfo?.changed_profiles?.[`${ownId}_0`] || ownInfo?.changed_profiles?.[ownId];
            ownAvatar = ownProfile?.avatar || null;
        } catch (e) { /* không crash */ }

        if (type === 'group') {
            // Nhóm: dùng API getGroupChatHistory
            const result = await account.api.getGroupChatHistory(threadId, count || 50);
            if (result && result.groupMsgs) {
                const uniqueUids = [...new Set(
                    result.groupMsgs
                        .map(m => m.data?.uidFrom)
                        .filter(uid => uid && uid !== '0' && uid !== ownId)
                )];
                if (uniqueUids.length > 0) {
                    try {
                        const userInfo = await account.api.getUserInfo(uniqueUids);
                        const profiles = userInfo?.changed_profiles || {};
                        for (const msg of result.groupMsgs) {
                            const uid = msg.data?.uidFrom;
                            if (msg.data && (msg.data.dName === null || msg.data.dName === undefined)) {
                                const profile = profiles[`${uid}_0`] || profiles[uid];
                                msg.data.dName = profile?.displayName || profile?.zaloName || uid;
                            }
                            // Gán avatar cho từng người gửi
                            if (msg.data && !msg.data._avatar) {
                                const profile = profiles[`${uid}_0`] || profiles[uid];
                                msg.data._avatar = profile?.avatar || null;
                            }
                        }
                    } catch (e) { /* không crash */ }
                }

                messages = result.groupMsgs.map(m => ({
                    id: m.data?.msgId || m.msgId,
                    from: m.data?.uidFrom,
                    name: m.data?.dName || 'Unknown',
                    avatar: m.data?._avatar || null,
                    content: typeof m.data?.content === 'string' ? m.data.content : (m.data?.content?.msg || ''),
                    ts: Number(m.data?.ts || 0),
                    isSelf: m.isSelf || m.data?.uidFrom === ownId
                }));
            }
        } else {
            // Cá nhân: load từ store
            messages = loadMessages(ownId, threadId);
        }

        messages.sort((a, b) => a.ts - b.ts);

        res.json({
            success: true,
            data: messages,
            ownAvatar,
            usedAccount: { ownId, phoneNumber: account.phoneNumber }
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

// ── Gửi tin nhắn ──────────────────────────────────────────────────────────
router.post('/send', async (req, res) => {
    try {
        const { message, threadId, type, accountSelection } = req.body;
        if (!message || !threadId) {
            return res.status(400).json({ error: 'message và threadId là bắt buộc' });
        }

        const account = getAccount(accountSelection);
        const msgType = type === 'group' ? ThreadType.Group : ThreadType.User;

        const result = await account.api.sendMessage(message, threadId, msgType);

        // Chỉ lưu vào store với chat cá nhân (nhóm đã có API riêng)
        if (msgType === ThreadType.User) {
            saveMessage(account.ownId, threadId, {
                id: result?.msgId || ('sent_' + Date.now()),
                from: account.ownId,
                name: 'Bạn',
                content: message,
                ts: Date.now(),
                isSelf: true
            });
        }

        res.json({
            success: true,
            data: result,
            usedAccount: { ownId: account.ownId, phoneNumber: account.phoneNumber }
        });
    } catch (error) {
        res.status(500).json({ success: false, error: error.message });
    }
});

export default router;
