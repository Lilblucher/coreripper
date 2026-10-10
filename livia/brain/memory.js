'use strict';
/**
 * Short conversation memory, per chat.
 *
 * Keeps the last N turns so replies stay coherent, stored through cache.js —
 * which means it lives in Redis on the data VPS when available (so context
 * survives a bot restart) and in-process otherwise. Bounded and TTL'd so it
 * can never grow without limit. Never throws.
 */

const cache = require('./cache');

const MAX_TURNS = Number(process.env.MEMORY_MAX_TURNS || 6); // user+assistant messages kept
const TTL_SEC = Number(process.env.MEMORY_TTL_SEC || 60 * 60 * 6); // 6h idle window

function key(chatId) {
  return `livia:mem:${chatId}`;
}

async function getHistory(chatId) {
  const arr = await cache.getJSON(key(chatId), []);
  return Array.isArray(arr) ? arr : [];
}

async function append(chatId, role, content) {
  if (!content) return;
  const hist = await getHistory(chatId);
  hist.push({ role, content: String(content).slice(0, 1000) });
  // keep only the most recent MAX_TURNS
  const trimmed = hist.slice(-MAX_TURNS);
  await cache.setJSON(key(chatId), trimmed, TTL_SEC);
}

async function clear(chatId) {
  await cache.del(key(chatId));
}

module.exports = { getHistory, append, clear, MAX_TURNS };
