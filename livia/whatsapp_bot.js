'use strict';
// Load environment (.env) before anything reads process.env.
try { require('dotenv').config({ path: require('path').join(__dirname, '.env') }); } catch (_e) {}

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const fs = require('fs');
const path = require('path');

const { getReply } = require('./brain/reply');
const cache = require('./brain/cache');
const memory = require('./brain/memory');
const knowledge = require('./brain/knowledge');

const BOT_NAME = process.env.BOT_NAME || 'Livia';
// DM behaviour: 'all' = reply to every direct message (default, most social);
// 'named' = only reply in DMs when addressed by name. Groups are always named-only.
const DM_MODE = (process.env.LIVIA_DM_MODE || 'all').toLowerCase();
const SEND_API_PORT = Number(process.env.SEND_API_PORT || 3001);
const SEND_API_HOST = process.env.SEND_API_HOST || '127.0.0.1';
// Flood guard: ignore a sender past this many messages inside the window.
const FLOOD_MAX = Number(process.env.FLOOD_MAX || 6);
const FLOOD_WINDOW_SEC = Number(process.env.FLOOD_WINDOW_SEC || 10);

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: path.join(__dirname, 'sessions') }),
  puppeteer: {
    headless: true,
    executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome-stable',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  },
});

let clientReady = false;
let botId = null; // our own WhatsApp id, for mention detection

client.on('qr', (qr) => {
  console.log('--- SCAN THIS QR CODE WITH YOUR WHATSAPP TO CONNECT THE BOT ---');
  qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
  clientReady = true;
  try { botId = client.info && client.info.wid && client.info.wid._serialized; } catch (_e) {}
  console.log(`${BOT_NAME} WhatsApp gateway is online! (DM mode: ${DM_MODE}, cache: ${cache.status().backend})`);
});

// =============================================================================
// 📡 INTERNAL SEND API — lets other local services (e.g. CoreRipper's Django
// monitors) send an outbound WhatsApp message through this authenticated
// session. Bound to localhost by default; keep it off any public interface.
//
//   POST /send  { "number": "15551234567", "message": "..." }
// Contract preserved for backend/monitors/whatsapp.py: connection refused = bot
// down, 503 = up but not linked, 400 on empty body = ready.
// =============================================================================
const sendApi = express();
sendApi.use(express.json());

sendApi.post('/send', async (req, res) => {
  if (!clientReady) {
    return res.status(503).json({ status: 'error', message: 'WhatsApp client is not ready yet.' });
  }
  const { number, message } = req.body || {};
  const digits = String(number || '').replace(/[^0-9]/g, '');
  if (!digits || !message) {
    return res.status(400).json({ status: 'error', message: "'number' and 'message' are required." });
  }
  try {
    await client.sendMessage(`${digits}@c.us`, message);
    res.json({ status: 'sent' });
  } catch (error) {
    console.error('❌ /send failed:', error.message);
    res.status(500).json({ status: 'error', message: error.message });
  }
});

sendApi.listen(SEND_API_PORT, SEND_API_HOST, () => {
  console.log(`📡 Internal send API listening on http://${SEND_API_HOST}:${SEND_API_PORT}`);
});

// =============================================================================
// 📢 MASS ANNOUNCEMENT SYSTEM (FILE WATCHER) — unchanged behaviour.
// =============================================================================
const announcementFilePath = path.join(__dirname, 'announcement.txt');
if (!fs.existsSync(announcementFilePath)) {
  fs.writeFileSync(announcementFilePath, '', 'utf8');
}
fs.watchFile(announcementFilePath, { interval: 1000 }, async (curr, prev) => {
  if (curr.mtime <= prev.mtime) return;
  try {
    const text = fs.readFileSync(announcementFilePath, 'utf8').trim();
    if (!text) return;
    console.log(`📢 Target Announcement Detected: "${text}"`);
    const targetGroupId = process.env.ANNOUNCE_GROUP_ID || '120363422734230937@g.us';
    const chat = await client.getChatById(targetGroupId);
    if (chat.isGroup) {
      const announcementText = `📢 *@all* \n\n${text}`;
      const participantIds = chat.participants.map((p) => p.id._serialized);
      await client.sendMessage(targetGroupId, announcementText, { mentions: participantIds });
      console.log('✅ Mass announcement sent.');
      fs.writeFileSync(announcementFilePath, '', 'utf8');
    }
  } catch (error) {
    console.error('❌ Announcement pipeline failure:', error.message);
  }
});

// =============================================================================
// Trigger helpers
// =============================================================================
// Does the message address the bot — by name, @mention, or by quoting one of
// the bot's own messages?
function nameRegex() {
  // word-boundary, case-insensitive match on the bot name
  return new RegExp(`\\b${BOT_NAME.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
}

function stripLeadingName(text) {
  // Remove a leading "Livia" / "Livia," / "Livia:" / "hey Livia" address so the
  // brain gets the real question.
  const re = new RegExp(`^(hey |hi |yo |ok |okay )?${BOT_NAME}[\\s,:!-]*`, 'i');
  return text.replace(re, '').trim() || text.trim();
}

async function addressesBot(msg, body) {
  if (botId && Array.isArray(msg.mentionedIds) && msg.mentionedIds.includes(botId)) return true;
  if (nameRegex().test(body)) return true;
  if (msg.hasQuotedMsg) {
    try {
      const quoted = await msg.getQuotedMessage();
      if (quoted && quoted.fromMe) return true;
    } catch (_e) {}
  }
  return false;
}

// Simple per-sender flood guard (silent). Uses the shared cache.
async function isFlooding(sender) {
  const key = `livia:flood:${sender}`;
  const now = Date.now();
  const times = (await cache.getJSON(key, [])).filter(
    (t) => now - t < FLOOD_WINDOW_SEC * 1000
  );
  times.push(now);
  await cache.setJSON(key, times, FLOOD_WINDOW_SEC);
  return times.length > FLOOD_MAX;
}

// =============================================================================
// MAIN INBOUND CHAT DISPATCHER (text only in Phase 1)
// =============================================================================
client.on('message', async (msg) => {
  try {
    if (msg.fromMe) return;

    const body = (msg.body || '').trim();
    if (!body) return; // ignore pure media/stickers/calls for now

    const chat = await msg.getChat();
    const isGroup = chat.isGroup;

    // Decide whether this message is for us.
    let shouldRespond = false;
    if (isGroup) {
      shouldRespond = await addressesBot(msg, body); // groups: named/mention/quote only
    } else {
      shouldRespond = DM_MODE === 'all' ? true : await addressesBot(msg, body);
    }
    if (!shouldRespond) return;

    // Flood guard (skip silently, don't burn quota or spam).
    if (await isFlooding(msg.from)) {
      console.log(`⏳ Skipping ${msg.from} (flooding).`);
      return;
    }

    const question = stripLeadingName(body);

    // Typing indicator for a natural feel (best-effort).
    try { await chat.sendStateTyping(); } catch (_e) {}

    const reply = await getReply(msg.from, question);

    try { await chat.clearState(); } catch (_e) {}
    await msg.reply(reply);
    console.log(`🤖 ${BOT_NAME} -> ${msg.from}: "${reply.slice(0, 60)}"`);
  } catch (error) {
    // The reply pipeline already guarantees graceful output; this guards the
    // dispatcher itself. Never surface an error to the chat.
    console.error('❌ Dispatcher error:', error && error.message);
  }
});

// =============================================================================
// NEW MEMBER WELCOME (brand-neutral, friendly)
// =============================================================================
client.on('group_join', async (notification) => {
  try {
    const chat = await notification.getChat();
    for (const memberId of notification.recipientIds) {
      const cleanNumber = memberId.split('@')[0];
      const welcome =
        `Welcome, @${cleanNumber}! 🎉\n\nI'm *${BOT_NAME}*, Clive's assistant. ` +
        `Say my name anytime and I'll jump in. 🙂`;
      await chat.sendMessage(welcome, { mentions: [memberId] });
    }
  } catch (error) {
    console.error('❌ Welcome error:', error && error.message);
  }
});

client.initialize();
