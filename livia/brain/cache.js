'use strict';
/**
 * Caching + shared-state layer for Livia.
 *
 * Backed by Redis (on the DATA VPS) when REDIS_URL is set, with a transparent
 * in-memory TTL fallback. Core resilience rule of this project: a cache outage
 * must degrade ONLY caching — it must never throw into the chat path. Every
 * method below swallows backend errors and falls back to the in-process Map, so
 * the bot keeps talking even if the data VPS is unreachable.
 *
 * Used for: the LLM response cache, per-provider 429 cooldown flags, per-sender
 * flood state, and conversation memory (see memory.js).
 */

const REDIS_URL = process.env.REDIS_URL || '';

// ---- in-memory fallback store (also the only store when no REDIS_URL) --------
const mem = new Map(); // key -> { value: string, expiresAt: number|null }

function memGet(key) {
  const row = mem.get(key);
  if (!row) return null;
  if (row.expiresAt !== null && row.expiresAt <= Date.now()) {
    mem.delete(key);
    return null;
  }
  return row.value;
}
function memSet(key, value, ttlSec) {
  mem.set(key, {
    value,
    expiresAt: ttlSec && ttlSec > 0 ? Date.now() + ttlSec * 1000 : null,
  });
}
// Opportunistic sweep so the Map can't grow without bound in fallback mode.
setInterval(() => {
  const now = Date.now();
  for (const [k, row] of mem) {
    if (row.expiresAt !== null && row.expiresAt <= now) mem.delete(k);
  }
}, 60 * 1000).unref();

// ---- optional Redis client ---------------------------------------------------
let redis = null;
let redisUp = false;
let warnedDown = false;

if (REDIS_URL) {
  try {
    // Lazy require so the bot still boots if ioredis isn't installed yet.
    const Redis = require('ioredis');
    redis = new Redis(REDIS_URL, {
      lazyConnect: false,
      maxRetriesPerRequest: 1,
      enableOfflineQueue: false,
      connectTimeout: 4000,
      retryStrategy: (times) => Math.min(times * 500, 5000), // keep trying to reconnect
    });
    redis.on('ready', () => {
      redisUp = true;
      warnedDown = false;
      console.log('🗄️  Cache: connected to Redis (data VPS).');
    });
    redis.on('end', () => { redisUp = false; });
    redis.on('error', (err) => {
      redisUp = false;
      if (!warnedDown) {
        warnedDown = true;
        console.error('🗄️  Cache: Redis unavailable, using in-memory fallback. ' + (err && err.message));
      }
    });
  } catch (err) {
    console.error('🗄️  Cache: ioredis not available, using in-memory fallback. ' + (err && err.message));
    redis = null;
  }
} else {
  console.log('🗄️  Cache: no REDIS_URL set — using in-memory cache only.');
}

// ---- public API (always resolves, never throws) -----------------------------
async function get(key) {
  if (redis && redisUp) {
    try { return await redis.get(key); }
    catch (_e) { /* fall through to memory */ }
  }
  return memGet(key);
}

async function set(key, value, ttlSec) {
  const v = String(value);
  if (redis && redisUp) {
    try {
      if (ttlSec && ttlSec > 0) await redis.set(key, v, 'EX', Math.ceil(ttlSec));
      else await redis.set(key, v);
      return;
    } catch (_e) { /* fall through to memory */ }
  }
  memSet(key, v, ttlSec);
}

async function del(key) {
  if (redis && redisUp) {
    try { await redis.del(key); return; }
    catch (_e) { /* fall through */ }
  }
  mem.delete(key);
}

// JSON convenience wrappers for memory.js and friends.
async function getJSON(key, fallback = null) {
  const raw = await get(key);
  if (raw == null) return fallback;
  try { return JSON.parse(raw); }
  catch (_e) { return fallback; }
}
async function setJSON(key, obj, ttlSec) {
  await set(key, JSON.stringify(obj), ttlSec);
}

function status() {
  return { backend: redis ? (redisUp ? 'redis' : 'redis-down(fallback)') : 'memory' };
}

module.exports = { get, set, del, getJSON, setJSON, status };
