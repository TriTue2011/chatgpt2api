// api.js — REST API client

const BASE = window.INGRESS_PATH || '';

async function request(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(BASE + path, opts);
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || data.message || 'Lỗi API');
    return data;
}

export async function fetchAccounts() {
    const data = await request('GET', '/api/accounts');
    return data.data || [];
}

export async function fetchConversations(accountSelection) {
    const data = await request('POST', '/api/conversations', { accountSelection });
    return data;
}

export async function fetchMessages(accountSelection, threadId, type, count = 50) {
    const data = await request('POST', '/api/messages', {
        accountSelection, threadId, type, count
    });
    return data;
}

export async function sendMessage(accountSelection, threadId, message, type) {
    const data = await request('POST', '/api/send', {
        accountSelection, threadId, message, type
    });
    return data;
}
