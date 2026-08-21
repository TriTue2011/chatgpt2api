// Hop dong du lieu chung giua Home Assistant, gateway Python va zca-js.
// Zalo ID thuong lon hon Number.MAX_SAFE_INTEGER, vi vay moi ID phai duoc
// giu dang chuoi tu luc JSON duoc parse den khi goi SDK.

const ZALO_ID_KEYS = new Set([
  'threadId', 'threadID', 'groupId', 'userId', 'memberId', 'friendId',
  'ownId', 'uid', 'uidFrom', 'idTo', 'conversationId',
  'msgId', 'cliMsgId', 'globalMsgId', 'ownerId', 'actionId',
  'reminderId', 'topicId', 'photoId',
]);

const ZALO_ID_LIST_KEYS = new Set([
  'threadIds', 'groupIds', 'userIds', 'memberIds', 'friendIds', 'msgIds',
]);

function normalizeId(value, key) {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) {
    throw new Error(
      `${key} vuot gioi han so nguyen an toan cua JavaScript; hay gui ID duoi dang chuoi JSON.`,
    );
  }
  const text = String(value).trim();
  return text.toLowerCase().startsWith('zalo:') ? text.slice(5) : text;
}

export function normalizeZaloIdsInPlace(value, key = '') {
  if (value === null || value === undefined) return value;

  if (ZALO_ID_KEYS.has(key)) return normalizeId(value, key);

  if (ZALO_ID_LIST_KEYS.has(key)) {
    const list = Array.isArray(value) ? value : [value];
    return list.map((item) => normalizeId(item, key));
  }

  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      value[index] = normalizeZaloIdsInPlace(value[index]);
    }
    return value;
  }

  if (typeof value === 'object') {
    for (const [childKey, childValue] of Object.entries(value)) {
      value[childKey] = normalizeZaloIdsInPlace(childValue, childKey);
    }
  }
  return value;
}

export const AUTO_DELETE_TTLS = Object.freeze({
  OFF: 0,
  ONE_DAY: 86_400_000,
  SEVEN_DAYS: 604_800_000,
  FOURTEEN_DAYS: 1_209_600_000,
});

const AUTO_DELETE_ALIASES = new Map([
  ['0', AUTO_DELETE_TTLS.OFF],
  ['off', AUTO_DELETE_TTLS.OFF],
  ['none', AUTO_DELETE_TTLS.OFF],
  ['disable', AUTO_DELETE_TTLS.OFF],
  ['disabled', AUTO_DELETE_TTLS.OFF],
  ['1d', AUTO_DELETE_TTLS.ONE_DAY],
  ['1day', AUTO_DELETE_TTLS.ONE_DAY],
  ['day', AUTO_DELETE_TTLS.ONE_DAY],
  ['86400000', AUTO_DELETE_TTLS.ONE_DAY],
  ['7d', AUTO_DELETE_TTLS.SEVEN_DAYS],
  ['7days', AUTO_DELETE_TTLS.SEVEN_DAYS],
  ['604800000', AUTO_DELETE_TTLS.SEVEN_DAYS],
  ['14d', AUTO_DELETE_TTLS.FOURTEEN_DAYS],
  ['14days', AUTO_DELETE_TTLS.FOURTEEN_DAYS],
  ['1209600000', AUTO_DELETE_TTLS.FOURTEEN_DAYS],
]);

const MESSAGE_TTL_ALIASES = new Map(AUTO_DELETE_ALIASES);
for (let hour = 1; hour <= 24; hour += 1) {
  MESSAGE_TTL_ALIASES.set(`${hour}h`, hour * 60 * 60 * 1000);
}

const VALID_AUTO_DELETE_TTLS = new Set(Object.values(AUTO_DELETE_TTLS));

function lookupTtl(raw, aliases) {
  return aliases.get(String(raw).trim().toLowerCase());
}

export function normalizeMessageTtl(rawTtl) {
  if (rawTtl === undefined || rawTtl === null || rawTtl === '') return null;
  const alias = lookupTtl(rawTtl, MESSAGE_TTL_ALIASES);
  const ttl = alias === undefined ? Number(rawTtl) : alias;
  if (!Number.isFinite(ttl) || !Number.isInteger(ttl) || ttl < 0) {
    throw new Error(
      'ttl tin nhan khong hop le. Dung off/0, 1h..24h, 1d, 7d, 14d hoac so milliseconds >= 0.',
    );
  }
  return ttl;
}

export function normalizeAutoDeleteTtl(rawTtl) {
  if (rawTtl === undefined || rawTtl === null || rawTtl === '') return null;
  const alias = lookupTtl(rawTtl, AUTO_DELETE_ALIASES);
  const ttl = alias === undefined ? Number(rawTtl) : alias;
  if (!Number.isFinite(ttl) || !Number.isInteger(ttl) || !VALID_AUTO_DELETE_TTLS.has(ttl)) {
    throw new Error(
      'ttl Auto Delete khong duoc ho tro. Dung off/0, 1d, 7d hoac 14d.',
    );
  }
  return ttl;
}

export function normalizeThreadType(type) {
  if (type === undefined || type === null || type === '') return 0;
  if (type === 0 || type === 1) return type;
  const normalized = String(type).trim().toLowerCase();
  if (normalized === 'user' || normalized === '0') return 0;
  if (normalized === 'group' || normalized === '1') return 1;
  throw new Error('type khong hop le. Dung "user"/0 hoac "group"/1.');
}

export function getRequestedMessageTtl(body = {}, message) {
  if (Object.prototype.hasOwnProperty.call(body, 'ttl')) return body.ttl;
  if (message && typeof message === 'object'
      && Object.prototype.hasOwnProperty.call(message, 'ttl')) {
    return message.ttl;
  }
  return undefined;
}

export function withMessageTtl(message, rawTtl) {
  const ttl = normalizeMessageTtl(rawTtl);
  if (ttl === null) {
    return message && typeof message === 'object' && !Array.isArray(message)
      ? { ...message }
      : message;
  }
  if (typeof message === 'string') return { msg: message, ttl };
  if (message && typeof message === 'object' && !Array.isArray(message)) {
    return { ...message, ttl };
  }
  return message;
}

export function messageTtlResult(rawTtl) {
  const ttl = normalizeMessageTtl(rawTtl);
  if (ttl === null) return null;
  return { enabled: ttl !== 0, ttl, scope: 'message' };
}

export function enrichMessageEvent(message, accountId) {
  const threadId = message?.threadId == null ? '' : String(message.threadId);
  const threadType = Number(message?.type);
  return {
    ...message,
    ...(threadId ? { threadId, _threadRef: `zalo:${threadId}` } : {}),
    ...((threadType === 0 || threadType === 1) ? { _threadType: threadType } : {}),
    _accountId: String(accountId ?? ''),
  };
}

export function filterReceivedFriendRequests(result) {
  const source = result && typeof result === 'object' ? result : {};
  const items = Array.isArray(source.recommItems) ? source.recommItems : [];
  const received = items.filter((item) => Number(
    item?.dataInfo?.recommType ?? item?.recommType,
  ) === 2);
  return { ...source, recommItems: received, total: received.length };
}
