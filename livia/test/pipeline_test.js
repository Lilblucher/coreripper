'use strict';
/**
 * Verifies the reply pipeline's resilience guarantees WITHOUT any API keys:
 *  - a known message gets a real offline-brain answer
 *  - gibberish degrades to a curated last-resort line
 *  - a broken offline brain (bad PYTHON_PATH) still degrades to last-resort
 *  - at NO point does forbidden/internal text (429, 404, "API key", stack
 *    traces, etc.) appear in a reply
 *  - the cache + memory layers round-trip
 *
 * Run: node test/pipeline_test.js   (or `npm test`)
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

// Ensure the "no providers" path (so we exercise offline + last-resort).
delete process.env.GROQ_API_KEY;
delete process.env.GEMINI_API_KEY;
delete process.env.REDIS_URL; // use in-memory cache

const FORBIDDEN = [
  /\b429\b/, /\b404\b/, /\b50\d\b/,
  /api[\s_-]?key/i, /\bapikey\b/i,
  /\bError\b/, /\bException\b/, /traceback/i, /\bstack\b/i,
  /undefined/, /\[object Object\]/,
  /__LIVIA_UNSURE__/,
];

function assertClean(label, reply) {
  assert(typeof reply === 'string' && reply.trim().length > 0, `${label}: empty reply`);
  for (const re of FORBIDDEN) {
    assert(!re.test(reply), `${label}: reply leaked forbidden text (${re}): "${reply}"`);
  }
}

function lastResortPool() {
  const raw = fs.readFileSync(path.join(__dirname, '..', 'knowledge', 'last_resort.md'), 'utf8');
  return new Set(
    raw.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#') && !l.startsWith('>'))
  );
}

(async () => {
  let failures = 0;
  const pool = lastResortPool();

  const { getReply } = require('../brain/reply');
  const cache = require('../brain/cache');
  const memory = require('../brain/memory');

  // 1) cache round-trip
  await cache.set('t:k', 'v', 30);
  assert.strictEqual(await cache.get('t:k'), 'v', 'cache get/set failed');
  console.log('✓ cache round-trips (backend:', cache.status().backend + ')');

  // 2) memory round-trip
  await memory.clear('t:chat');
  await memory.append('t:chat', 'user', 'hi');
  const hist = await memory.getHistory('t:chat');
  assert(hist.length === 1 && hist[0].content === 'hi', 'memory append/get failed');
  console.log('✓ memory round-trips');

  // 3) known message -> real offline answer (not a last-resort filler)
  for (const q of ['hey there', 'who are you', 'send me his links', 'thanks a lot']) {
    const r = await getReply('t:chatA', q);
    assertClean('known("' + q + '")', r);
    assert(!pool.has(r), `known("${q}") unexpectedly returned a last-resort line: "${r}"`);
    console.log(`✓ offline brain answered "${q}" -> "${r.slice(0, 50)}"`);
  }

  // 4) gibberish -> last-resort line (offline brain is unsure)
  {
    const r = await getReply('t:chatB', 'zxqw plok mmnf 00x');
    assertClean('gibberish', r);
    assert(pool.has(r), `gibberish should return a last-resort line, got: "${r}"`);
    console.log(`✓ gibberish -> last-resort: "${r}"`);
  }

  // 5) broken offline brain (bad PYTHON_PATH) + no keys -> last-resort, in a
  //    child process so the module-level PYTHON binding picks up the bad path.
  {
    const script = `
      process.env.PYTHON_PATH='/nonexistent/python-xyz';
      delete process.env.GROQ_API_KEY; delete process.env.GEMINI_API_KEY; delete process.env.REDIS_URL;
      const { getReply } = require('${path.join(__dirname, '..', 'brain', 'reply.js').replace(/\\/g, '\\\\')}');
      getReply('t:chatC','hello there').then(r => { process.stdout.write('<<<REPLY>>>' + r + '<<<END>>>'); });
    `;
    const raw = execFileSync(process.execPath, ['-e', script], { encoding: 'utf8', timeout: 20000 });
    const m = raw.match(/<<<REPLY>>>([\s\S]*?)<<<END>>>/);
    assert(m, `broken-brain: could not parse reply from child output: "${raw}"`);
    const out = m[1].trim();
    assertClean('broken-brain', out);
    assert(pool.has(out), `broken brain should return a last-resort line, got: "${out}"`);
    console.log(`✓ broken offline brain -> last-resort: "${out}"`);
  }

  if (failures === 0) {
    console.log('\nALL PIPELINE TESTS PASSED ✅');
    process.exit(0);
  }
})().catch((err) => {
  console.error('\nPIPELINE TEST FAILED ❌\n', err && err.message);
  process.exit(1);
});
