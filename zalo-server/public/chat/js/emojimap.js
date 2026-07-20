// emojimap.js — Load emoticon-to-emoji data từ CDN
const TREE_URL = 'https://cdn.jsdelivr.net/npm/emoticon-to-emoji@0.1.9/tree.json';

let trie = null;
let ready = false;
let pending = null;

export async function initEmoticonConverter() {
    if (ready) return;
    if (pending) return pending;
    pending = fetch(TREE_URL).then(r => r.json()).then(data => {
        trie = data;
        ready = true;
    }).catch(e => {
        console.warn('Emoticon tree load failed:', e.message);
        pending = null;  // Allow retry on next call
    });
    return pending;
}

export function convertEmoticons(text) {
    if (!trie) return text;
    let result = '';
    let i = 0;
    while (i < text.length) {
        let node = trie;
        let j = i;
        let found = null;
        while (j < text.length && node) {
            const next = node[text[j]];
            if (!next) break;
            node = next;
            j++;
            if (node.M) found = { end: j, emoji: node.M };
        }
        if (found) { result += found.emoji; i = found.end; }
        else { result += text[i]; i++; }
    }
    return result;
}
