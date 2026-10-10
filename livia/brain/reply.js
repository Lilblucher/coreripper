'use strict';
/**
 * The reply pipeline — the one function the WhatsApp dispatcher calls.
 *
 *   LLM (Groq -> Gemini)  ->  offline Python brain  ->  last-resort line
 *
 * Guarantees, by construction:
 *  - Always resolves to a non-empty, human-friendly string.
 *  - The ENTIRE path is wrapped so even an unexpected crash returns a
 *    last-resort line, never an error, a stack trace, or a status code.
 *  - No "429 / 404 / API key / Error" text can leak to the user: the LLM layer
 *    returns null (not an error string) on failure, and the offline/last-resort
 *    layers only ever return curated copy.
 */

const { execFile } = require('child_process');
const path = require('path');

const knowledge = require('./knowledge');
const memory = require('./memory');
const llm = require('./llm');

const PYTHON = process.env.PYTHON_PATH || 'python3';
const BRAIN_SCRIPT = path.join(__dirname, '..', 'train_brain.py');
const BRAIN_TIMEOUT_MS = Number(process.env.BRAIN_TIMEOUT_MS || 8000);
const LOW_CONFIDENCE_SENTINEL = '__LIVIA_UNSURE__';

/** Run the offline stdlib brain. Resolves to a reply string or null. Never rejects. */
function offlineBrain(userMessage) {
  return new Promise((resolve) => {
    execFile(
      PYTHON,
      [BRAIN_SCRIPT, userMessage],
      { timeout: BRAIN_TIMEOUT_MS },
      (err, stdout) => {
        if (err) {
          console.error(`🧠 offline brain failed: ${err.message}`);
          return resolve(null);
        }
        const out = (stdout || '').trim();
        if (!out || out === LOW_CONFIDENCE_SENTINEL) return resolve(null);
        resolve(out);
      }
    );
  });
}

/**
 * Produce Livia's reply to one message.
 * @param {string} chatId      stable id for this conversation (for memory)
 * @param {string} userMessage the user's text
 * @returns {Promise<string>}  always a friendly, non-empty reply
 */
async function getReply(chatId, userMessage) {
  const text = (userMessage || '').trim();
  if (!text) return knowledge.randomLastResort();

  try {
    // 1) Try the smart path (LLM with persona + knowledge + recent context).
    const history = await memory.getHistory(chatId);
    const aiReply = await llm.generate({
      systemPrompt: knowledge.getSystemPrompt(),
      promptHash: knowledge.getPromptHash(),
      history,
      userMessage: text,
    });

    let reply = aiReply;

    // 2) Offline brain fallback (APIs down/rate-limited/unconfigured).
    if (!reply) {
      reply = await offlineBrain(text);
    }

    // 3) Last-resort safety net.
    if (!reply) {
      reply = knowledge.randomLastResort();
      // Don't poison memory with a filler line.
      return reply;
    }

    // Record the exchange for continuity (best-effort).
    await memory.append(chatId, 'user', text);
    await memory.append(chatId, 'assistant', reply);
    return reply;
  } catch (err) {
    // Absolute catch-all: a bug here must still degrade gracefully.
    console.error(`🧠 reply pipeline crashed: ${err && err.stack ? err.stack : err}`);
    return knowledge.randomLastResort();
  }
}

module.exports = { getReply };
