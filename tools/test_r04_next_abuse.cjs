/* R04 Next.js transport bounds: isolated TypeScript evaluation, no real network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const repo = path.resolve(__dirname, '..');
let ts;
try { ts = require(path.join(repo, 'apps/web/node_modules/typescript')); }
catch { ts = require(process.env.NODE_PATH ? path.join(process.env.NODE_PATH, 'typescript') : 'typescript'); }
const sessionFile = path.join(repo, 'apps/web/src/app/api/session/[action]/route.ts');
const runtimeFile = path.join(repo, 'apps/web/src/app/runtime/[runtimeId]/[[...assetPath]]/route.ts');
function transpile(file) {
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true,
  });
  assert.deepEqual((code.diagnostics || []).filter(x => x.category === ts.DiagnosticCategory.Error), []);
  return code.outputText;
}
const compiled = transpile(sessionFile);
const runtimeCode = transpile(runtimeFile);
assert.match(runtimeCode, /AbortSignal\.timeout\(30000\)/);

class MockResponse {
  constructor(body, options={}) { this.body = body; this.status = options.status ?? 200; this.headers = new Headers(options.headers); }
  static json(value, options={}) { return new MockResponse(JSON.stringify(value), options); }
}
function makeApp() {
  const calls=[];
  const mod={exports:{}};
  vm.runInNewContext(compiled, {
    module:mod, exports:mod.exports, URL, Headers, Set, Promise, Uint8Array, TextDecoder, AbortSignal, Number,
    process:{env:{NODE_ENV:'development'}},
    require:name=>{ if(name==='next/server') return {NextResponse:MockResponse}; throw new Error(name); },
    fetch:async(url,opts)=> { calls.push({url,opts}); return {status:200,text:async()=>'{"ok":true}',headers:new Headers({'content-type':'application/json'})}; },
  }, {filename:sessionFile});
  return {POST:mod.exports.POST,calls};
}
function makeRequest(body, declared=null) {
  const content = typeof body==='string' ? new TextEncoder().encode(body) : body;
  const stream = new ReadableStream({start(controller){if(content?.length) controller.enqueue(content); controller.close();}});
  const headers = new Headers({host:'localhost:3000',origin:'http://localhost:3000','x-augmis-csrf':'1'});
  if(declared!==null) headers.set('content-length',String(declared));
  return {url:'http://localhost:3000/api/session/login', headers, body:stream};
}
async function test() {
  const ctx={params:Promise.resolve({action:'login'})};
  const app=makeApp();
  const valid='{"email":"test@example.test","password":"test-only"}';
  assert.equal((await app.POST(makeRequest(valid),ctx)).status,200);
  assert.equal(app.calls[0].opts.body,valid, 'The exact login body must survive chunked decode');
  assert.ok(app.calls[0].opts.signal instanceof AbortSignal);
  assert.equal(app.calls[0].opts.signal.aborted,false);
  assert.equal((await app.POST(makeRequest('x'.repeat(8193)),ctx)).status,413);
  assert.equal((await app.POST(makeRequest('x',100000),ctx)).status,413);
  assert.equal(app.calls.length,1, 'Oversized login must never reach FastAPI');
  const bad=makeRequest(new Uint8Array([0xc3,0x28]));
  assert.equal((await app.POST(bad,ctx)).status,400);
  assert.equal(app.calls.length,1);
  console.log('R04 Next transport: bounded login, upstream deadline, oversized/invalid-body denial verified');
}
test().catch(e=>{console.error(e);process.exitCode=1;});
