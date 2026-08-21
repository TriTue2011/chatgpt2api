import fs from 'node:fs';
import path from 'node:path';
import { getDataDirectory } from '../config/addon.js';
import { writeFileAtomicSync } from './atomicFile.js';

const DEFAULT_MAX_MESSAGES = 5000;
const DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024;
const pendingWrites = new Map();
const flushTimers = new Map();

function safePart(value) {
  return String(value ?? '').replace(/[^a-zA-Z0-9._-]/g, '_');
}

function historyFile(ownId, groupId) {
  const directory = path.join(
    getDataDirectory(), 'history', 'groups', safePart(ownId),
  );
  fs.mkdirSync(directory, { recursive: true });
  return path.join(directory, `${safePart(groupId)}.jsonl`);
}

function stringify(value) {
  return JSON.stringify(
    value,
    (_key, current) => (typeof current === 'bigint' ? current.toString() : current),
  );
}

function cloneSerializable(value) {
  try {
    return JSON.parse(stringify(value));
  } catch {
    return {
      threadId: value?.threadId,
      type: value?.type,
      isSelf: value?.isSelf,
      data: value?.data ?? null,
    };
  }
}

function messageKey(message) {
  const data = message?.data || {};
  const messageId = data.msgId ?? data.msgID ?? message?.msgId ?? '';
  const clientId = data.cliMsgId ?? data.cliMsgID ?? message?.cliMsgId ?? '';
  const sender = data.uidFrom ?? data.uid ?? '';
  const timestamp = data.ts ?? data.time ?? message?._storedAt ?? '';
  if (messageId || clientId) return `${messageId}:${clientId}:${sender}`;
  return `${sender}:${timestamp}:${stringify(data.content ?? '')}`;
}

function parseFile(file) {
  if (!fs.existsSync(file)) return [];
  const messages = [];
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { messages.push(JSON.parse(line)); } catch { /* bo record dang do */ }
  }
  return messages;
}

function deduplicate(messages) {
  const seen = new Set();
  return messages.filter((message) => {
    const key = messageKey(message);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function positiveEnv(name, fallback) {
  const parsed = Number.parseInt(process.env[name] || '', 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function compact(file) {
  const maxMessages = positiveEnv('GROUP_HISTORY_MAX_MESSAGES', DEFAULT_MAX_MESSAGES);
  const kept = deduplicate(parseFile(file)).slice(-maxMessages);
  const content = kept.map(stringify).join('\n');
  writeFileAtomicSync(file, content ? `${content}\n` : '');
}

function flush(file) {
  const timer = flushTimers.get(file);
  if (timer) clearTimeout(timer);
  flushTimers.delete(file);
  const records = pendingWrites.get(file);
  if (!records?.length) return;
  pendingWrites.delete(file);
  try {
    fs.appendFileSync(file, records.join(''), { encoding: 'utf8', mode: 0o600 });
    const maxBytes = positiveEnv('GROUP_HISTORY_MAX_FILE_BYTES', DEFAULT_MAX_FILE_BYTES);
    if (fs.statSync(file).size > maxBytes) compact(file);
  } catch (error) {
    pendingWrites.set(file, [...records, ...(pendingWrites.get(file) || [])]);
    throw error;
  }
}

function scheduleFlush(file) {
  if (flushTimers.has(file)) return;
  const timer = setTimeout(() => {
    try { flush(file); } catch (error) {
      console.error(`[History] Khong ghi duoc ${file}: ${error.message}`);
      scheduleFlush(file);
    }
  }, 100);
  timer.unref?.();
  flushTimers.set(file, timer);
}

export function storeGroupMessage(ownId, message) {
  const groupId = message?.threadId;
  if (!ownId || !groupId) return false;
  try {
    const file = historyFile(ownId, groupId);
    const record = cloneSerializable(message);
    record._accountId = String(ownId);
    record._storedAt = Date.now();
    const queue = pendingWrites.get(file) || [];
    queue.push(`${stringify(record)}\n`);
    pendingWrites.set(file, queue);
    scheduleFlush(file);
    return true;
  } catch (error) {
    console.error(`[History] Khong queue duoc group ${groupId}: ${error.message}`);
    return false;
  }
}

export function getCachedGroupHistory(ownId, groupId, count = 50) {
  const safeCount = Math.min(Math.max(Number.parseInt(count, 10) || 50, 1), 200);
  const file = historyFile(ownId, groupId);
  flush(file);
  const parsedMessages = deduplicate(parseFile(file));
  const maxMessages = positiveEnv('GROUP_HISTORY_MAX_MESSAGES', DEFAULT_MAX_MESSAGES);
  const allMessages = parsedMessages.slice(-maxMessages);
  if (parsedMessages.length > maxMessages) compact(file);
  const selected = allMessages.slice(-safeCount);
  const latest = selected.at(-1)?.data || {};
  return {
    lastActionId: String(
      latest.msgId ?? latest.msgID ?? latest.cliMsgId ?? latest.cliMsgID ?? '',
    ),
    lastActionIdOther: '',
    more: allMessages.length > selected.length ? 1 : 0,
    groupMsgs: selected,
    source: 'local_persistent_cache',
    cachedCount: allMessages.length,
  };
}

export function flushAllGroupHistorySync() {
  for (const file of [...pendingWrites.keys()]) {
    try { flush(file); } catch (error) {
      console.error(`[History] Khong flush duoc ${file}: ${error.message}`);
    }
  }
}
