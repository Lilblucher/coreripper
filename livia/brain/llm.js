'use strict';
/**
 * LLM client for Livia: Groq (primary) with Gemini (fallback).
 *
 * Design rules (match the project's resilience philosophy):
 *  - NEVER throws to the caller. Returns a reply string, or null if no provider
 *    could answer (caller then falls back to the offline brain / last-resort).
 *  - All failures — unconfigured keys, 429s, timeouts, bad JSON — are logged to
 *    the console ONLY. No status code or "API key" text ever reaches a user.
 *  - Rate-limit aware: a 429 (or hard error) from a provider sets a short
 *    cooldown in the shared cache, so we stop hammering it and skip straight to
 *    the other provider until it cools off. Both keys are combined this way to
 *    stretch the free-tier limits.
 *  - A small response cache (shared via cache.js) short-circuits duplicate asks.
 *
 * Both providers are called over their OpenAI-compatible chat/completions
 * endpoints via global fetch (Node 18+). No SDK needed.
 */

const crypto = require('crypto');
const cache = require('./cache');

const GROQ_API_KEY = process.env.GROQ_API_KEY || '';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';

const GROQ_MODEL = process.env.GROQ_MODEL || 'llama-3.3-70b-versatile';
// gemini-flash-latest is the id proven to work on the free tier (see CoreRipper
// CLAUDE.md note); the dated flash ids 404 for new users.
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-flash-latest';

// Endpoints are overridable (self-hosting / testing); defaults are the real ones.
const GROQ_URL =
  process.env.GROQ_URL || 'https://api.groq.com/openai/v1/chat/completions';
const GEMINI_URL =
  process.env.GEMINI_URL ||
  'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions';

const REQUEST_TIMEOUT_MS = Number(process.env.LLM_TIMEOUT_MS || 12000);
const MAX_TOKENS = Number(process.env.LLM_MAX_TOKENS || 400);
const COOLDOWN_SEC = Number(process.env.LLM_COOLDOWN_SEC || 60); // after a 429
const CACHE_TTL_SEC = Number(process.env.LLM_CACHE_TTL_SEC || 900);

function cooldownKey(provider) { return `livia:cooldown:${provider}`; }

async function isCoolingDown(provider) {
  return (await cache.get(cooldownKey(provider))) !== null;
}
async function setCooldown(provider, seconds) {
  await cache.set(cooldownKey(provider), '1', seconds);
}

async function timedFetch(url, options) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

function buildMessages(systemPrompt, history, userMessage) {
  const messages = [{ role: 'system', content: systemPrompt }];
  for (const turn of history || []) {
    if (turn && turn.role && turn.content) {
      messages.push({ role: turn.role, content: turn.content });
    }
  }
  messages.push({ role: 'user', content: userMessage });
  return messages;
}

/**
 * Call one OpenAI-compatible provider. Returns { ok, text, rateLimited }.
 * Never throws.
 */
async function callOpenAICompatible({ label, url, apiKey, model, messages }) {
  if (!apiKey) {
    console.error(`🧠 LLM(${label}): not configured, skipping.`);
    return { ok: false, text: null, rateLimited: false };
  }
  try {
    const res = await timedFetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages,
        max_tokens: MAX_TOKENS,
        temperature: 0.8,
      }),
    });

    if (res.status === 429) {
      console.error(`🧠 LLM(${label}): rate limited (429), cooling down.`);
      return { ok: false, text: null, rateLimited: true };
    }
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      console.error(`🧠 LLM(${label}): HTTP ${res.status}. ${body.slice(0, 200)}`);
      // Treat 5xx like a temporary outage worth a short cooldown too.
      return { ok: false, text: null, rateLimited: res.status >= 500 };
    }

    const data = await res.json();
    const text =
      data &&
      data.choices &&
      data.choices[0] &&
      data.choices[0].message &&
      data.choices[0].message.content;
    if (!text || !String(text).trim()) {
      console.error(`🧠 LLM(${label}): empty content.`);
      return { ok: false, text: null, rateLimited: false };
    }
    return { ok: true, text: String(text).trim(), rateLimited: false };
  } catch (err) {
    console.error(`🧠 LLM(${label}): request failed. ${err && err.message}`);
    return { ok: false, text: null, rateLimited: false };
  }
}

/**
 * Generate a reply. Returns a string, or null if neither provider could answer.
 * @param {object} opts
 * @param {string} opts.systemPrompt
 * @param {string} opts.promptHash  version tag for the cache key
 * @param {Array}  opts.history     [{role, content}, ...] recent turns
 * @param {string} opts.userMessage
 */
async function generate({ systemPrompt, promptHash, history, userMessage }) {
  if (!GROQ_API_KEY && !GEMINI_API_KEY) {
    console.error('🧠 LLM: no provider keys configured — deferring to offline brain.');
    return null;
  }

  // Response cache (keyed on prompt version + recent context + message), so a
  // repeated question doesn't spend quota. History is included so context-
  // dependent replies aren't wrongly reused.
  const histSig = (history || []).map((h) => `${h.role}:${h.content}`).join('|');
  const cacheKey =
    'livia:resp:' +
    crypto
      .createHash('sha1')
      .update(`${promptHash}::${histSig}::${userMessage}`)
      .digest('hex');

  const cached = await cache.get(cacheKey);
  if (cached) return cached;

  const messages = buildMessages(systemPrompt, history, userMessage);

  // Provider order: Groq first unless it's cooling down, then Gemini.
  const providers = [
    {
      label: 'groq',
      url: GROQ_URL,
      apiKey: GROQ_API_KEY,
      model: GROQ_MODEL,
    },
    {
      label: 'gemini',
      url: GEMINI_URL,
      apiKey: GEMINI_API_KEY,
      model: GEMINI_MODEL,
    },
  ];

  for (const p of providers) {
    if (!p.apiKey) continue;
    if (await isCoolingDown(p.label)) {
      console.error(`🧠 LLM(${p.label}): in cooldown, skipping.`);
      continue;
    }
    const r = await callOpenAICompatible({ ...p, messages });
    if (r.ok) {
      await cache.set(cacheKey, r.text, CACHE_TTL_SEC);
      return r.text;
    }
    if (r.rateLimited) await setCooldown(p.label, COOLDOWN_SEC);
  }

  return null;
}

module.exports = { generate };
