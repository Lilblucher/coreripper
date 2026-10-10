'use strict';
/**
 * Exercises llm.js provider logic against LOCAL mock servers (no external
 * network): Groq-primary success, Groq-429 -> Gemini fallback + cooldown,
 * both-down -> null (so the pipeline would fall through to the offline brain),
 * and the response cache. Also checks cache.js degrades to memory when
 * REDIS_URL is set but ioredis is unavailable.
 */

const assert = require('assert');
const http = require('http');

// Local mock "OpenAI-compatible" endpoints. Behaviour is controlled per-request
// by the `mode` the test sets before calling.
function makeServer(stateRef) {
  return http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      stateRef.hits++;
      if (stateRef.mode === '429') {
        res.writeHead(429, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: { message: 'rate limit' } }));
      }
      if (stateRef.mode === '500') {
        res.writeHead(500);
        return res.end('server error');
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ choices: [{ message: { content: stateRef.reply } }] }));
    });
  });
}

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
}

(async () => {
  const groqState = { mode: 'ok', reply: 'GROQ_OK', hits: 0 };
  const gemState = { mode: 'ok', reply: 'GEMINI_OK', hits: 0 };
  const groqSrv = makeServer(groqState);
  const gemSrv = makeServer(gemState);
  const groqPort = await listen(groqSrv);
  const gemPort = await listen(gemSrv);

  process.env.GROQ_URL = `http://127.0.0.1:${groqPort}/`;
  process.env.GEMINI_URL = `http://127.0.0.1:${gemPort}/`;
  process.env.GROQ_API_KEY = 'test-groq';
  process.env.GEMINI_API_KEY = 'test-gemini';
  process.env.LLM_COOLDOWN_SEC = '60';
  delete process.env.REDIS_URL;

  const llm = require('../brain/llm');
  const baseArgs = { systemPrompt: 'sys', promptHash: 'v1', history: [] };

  // 1) Groq primary success
  let r = await llm.generate({ ...baseArgs, userMessage: 'q1' });
  assert.strictEqual(r, 'GROQ_OK', 'should use Groq when healthy');
  assert.strictEqual(gemState.hits, 0, 'Gemini should not be called when Groq works');
  console.log('✓ Groq primary success');

  // 2) cache hit (same prompt) -> no new provider hits
  const groqHitsBefore = groqState.hits;
  r = await llm.generate({ ...baseArgs, userMessage: 'q1' });
  assert.strictEqual(r, 'GROQ_OK', 'cache should return same answer');
  assert.strictEqual(groqState.hits, groqHitsBefore, 'cache hit should not call provider');
  console.log('✓ response cache short-circuits a repeat');

  // 3) Groq 429 -> Gemini fallback, and Groq enters cooldown
  groqState.mode = '429';
  r = await llm.generate({ ...baseArgs, userMessage: 'q2' });
  assert.strictEqual(r, 'GEMINI_OK', 'should fall back to Gemini on Groq 429');
  console.log('✓ Groq 429 -> Gemini fallback');

  // 4) next call: Groq is cooling down, so it is skipped entirely (0 new hits)
  const groqHits2 = groqState.hits;
  r = await llm.generate({ ...baseArgs, userMessage: 'q3' });
  assert.strictEqual(r, 'GEMINI_OK', 'still Gemini while Groq cools down');
  assert.strictEqual(groqState.hits, groqHits2, 'Groq should be skipped during cooldown');
  console.log('✓ Groq skipped during cooldown (quota-friendly)');

  // 5) both down -> null (pipeline would then use the offline brain)
  gemState.mode = '500';
  r = await llm.generate({ ...baseArgs, userMessage: 'q4' });
  assert.strictEqual(r, null, 'both providers failing should return null, never an error string');
  console.log('✓ both providers down -> null (no error leaked)');

  groqSrv.close();
  gemSrv.close();

  // 6) cache.js: REDIS_URL set but ioredis missing -> must degrade to memory,
  //    in a child process so the module initializes fresh with that env.
  {
    const { execFileSync } = require('child_process');
    const path = require('path');
    const cachePath = path.join(__dirname, '..', 'brain', 'cache.js').replace(/\\/g, '\\\\');
    const script = `
      process.env.REDIS_URL='redis://127.0.0.1:6399/0';
      const cache = require('${cachePath}');
      (async () => {
        await cache.set('x','y',10);
        const v = await cache.get('x');
        process.stdout.write('<<<'+v+'|'+cache.status().backend+'>>>');
        // one-shot: the daemon keeps the ioredis reconnect loop alive on purpose,
        // so a short script must exit explicitly.
        process.exit(0);
      })();
    `;
    const raw = execFileSync(process.execPath, ['-e', script], { encoding: 'utf8', timeout: 15000 });
    const m = raw.match(/<<<(.*?)>>>/);
    assert(m, 'could not parse cache child output: ' + raw);
    const [val] = m[1].split('|');
    assert.strictEqual(val, 'y', 'cache must still work (via memory) when ioredis/Redis is unavailable');
    console.log('✓ cache degrades to memory when Redis/ioredis unavailable (backend: ' + m[1].split('|')[1] + ')');
  }

  console.log('\nALL LLM TESTS PASSED ✅');
  process.exit(0);
})().catch((err) => {
  console.error('\nLLM TEST FAILED ❌\n', err && err.stack ? err.stack : err);
  process.exit(1);
});
