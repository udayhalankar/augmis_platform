/* R01 isolated contract tests for Next.js same-origin session relay.
 * Uses installed TypeScript only to transpile the existing route; no HTTP/DB/Docker I/O.
 * This is not a substitute for genuine ALB/staging E2E testing.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const repo = path.resolve(__dirname, '..');
let ts;
try { ts = require(path.join(repo, 'apps/web/node_modules/typescript')); }
catch { ts = require('typescript'); }
const filename = path.join(repo, 'apps/web/src/app/api/session/[action]/route.ts');
const transpiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  fileName: filename,
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  reportDiagnostics: true,
});
assert.equal((transpiled.diagnostics || []).filter(x => x.category === ts.DiagnosticCategory.Error).length, 0);

class MockResponse {
  constructor(body, options = {}) {
    this.body = body;
    this.status = options.status ?? 200;
    this.headers = new Headers(options.headers);
  }
  static json(value, options = {}) { return new MockResponse(JSON.stringify(value), options); }
}

function makeApp(env) {
  const calls = [];
  const mod = { exports: {} };
  vm.runInNewContext(transpiled.outputText, {
    module: mod, exports: mod.exports, URL, Headers, Set, Promise,
    AbortSignal, Uint8Array, TextDecoder,
    process: { env },
    require: name => {
      if (name === 'next/server') return { NextResponse: MockResponse };
      throw new Error('Unexpected runtime import: ' + name);
    },
    fetch: async (url, opts) => {
      calls.push({ url, opts });
      return { status: 200, text: async () => '{"access_token":"test"}',
        headers: new Headers({ 'Content-Type': 'application/json', 'Set-Cookie': '__Host-augmis_refresh=test; Secure; HttpOnly; Path=/' }) };
    },
  }, { filename });
  return { POST: mod.exports.POST, calls };
}

function request(host, origin, extra = {}) {
  return {
    url: 'http://untrusted-forwarded-host.local/api/session/login',
    headers: new Headers({ host, origin, 'x-augmis-csrf': '1', ...extra }),
    body: new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode('{"email":"test@example.invalid","password":"not-a-real-secret"}'));
      controller.close();
    } }),
  };
}

async function run() {
  const prod = { NODE_ENV: 'production', AUGMIS_PUBLIC_ORIGIN: 'https://portal.customer.com',
    AUGMIS_SESSION_API_URL: 'http://api.internal:8001', NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8001' };
  const app = makeApp(prod);
  const context = { params: Promise.resolve({ action: 'login' }) };
  assert.equal((await app.POST(request('portal.customer.com', prod.AUGMIS_PUBLIC_ORIGIN), context)).status, 200);
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].url, 'http://api.internal:8001/api/v1/auth/login');
  assert.equal(app.calls[0].opts.headers.Origin, prod.AUGMIS_PUBLIC_ORIGIN);

  const attacks = [
    request('attacker.example', prod.AUGMIS_PUBLIC_ORIGIN),
    request('portal.customer.com', 'https://attacker.example', { 'x-forwarded-host': 'portal.customer.com' }),
    request('attacker.example', 'https://attacker.example', { 'x-forwarded-host': 'portal.customer.com', 'x-forwarded-proto': 'https' }),
    request('portal.customer.com', prod.AUGMIS_PUBLIC_ORIGIN, { 'x-augmis-csrf': '0' }),
  ];
  for (const req of attacks) assert.equal((await app.POST(req, context)).status, 403);
  assert.equal(app.calls.length, 1, 'No attacker-supplied request reached the API');

  for (const bad of [
    { NODE_ENV: 'development', AUGMIS_APP_ENV: 'prodution' },
    { ...prod, AUGMIS_PUBLIC_ORIGIN: '' },
    { ...prod, AUGMIS_PUBLIC_ORIGIN: 'http://localhost:3000' },
    { ...prod, AUGMIS_SESSION_API_URL: '' },
    { ...prod, AUGMIS_SESSION_API_URL: 'http://127.0.0.1:8001' },
    { ...prod, AUGMIS_SESSION_API_URL: 'https://portal.customer.com' },
  ]) {
    const broken = makeApp(bad);
    assert.equal((await broken.POST(request('portal.customer.com', prod.AUGMIS_PUBLIC_ORIGIN), context)).status, 503);
    assert.equal(broken.calls.length, 0);
  }

  const dev = makeApp({ NODE_ENV: 'development' });
  const devReq = request('localhost:3000', 'http://localhost:3000');
  devReq.url = 'http://localhost:3000/api/session/login';
  assert.equal((await dev.POST(devReq, context)).status, 200);
  assert.equal(dev.calls[0].url, 'http://127.0.0.1:8001/api/v1/auth/login');
  console.log('R01 Next session transport: 11 positive/negative assertions passed');
}

run().catch(error => { console.error(error); process.exitCode = 1; });
