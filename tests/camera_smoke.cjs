const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const targets = await (await fetch(`http://127.0.0.1:${process.argv[2]}/json/list`)).json();
  const socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, {once: true}));
  let id = 0;
  const pending = new Map(), errors = [];
  socket.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails);
    if (!data.id) return;
    const handler = pending.get(data.id);
    pending.delete(data.id);
    data.error ? handler.reject(Error(JSON.stringify(data.error))) : handler.resolve(data.result);
  });
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const current = ++id;
      pending.set(current, {resolve, reject});
      socket.send(JSON.stringify({id: current, method, params}));
    });
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  async function waitFor(expression) {
    for (let attempt = 0; attempt < 100; attempt++) {
      try { if (await evaluate(expression)) return; } catch (_) {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('Timeout: ' + expression);
  }
  await call('Runtime.enable');
  await call('Network.enable');
  await call('Network.setExtraHTTPHeaders', {headers: {Authorization: 'Basic ' + Buffer.from('camera-reader:smoke-password').toString('base64')}});
  await call('Emulation.setDeviceMetricsOverride', {width: 1000, height: 760, deviceScaleFactor: 1, mobile: false});
  await call('Page.navigate', {url: process.argv[3]});
  await waitFor("document.getElementById('frame')?.naturalWidth > 0 && !document.getElementById('frame').hidden");
  await evaluate("document.getElementById('language').value='pt'; document.getElementById('language').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate('document.documentElement.lang'), 'pt');
  assert.equal(await evaluate("document.getElementById('status').textContent"), 'Ao vivo');
  const headers = await evaluate("fetch('/_camera/frame.jpg', {cache:'no-store'}).then(r => ({cache:r.headers.get('cache-control'), type:r.headers.get('content-type')}))");
  assert.match(headers.cache, /no-store/);
  assert.equal(headers.type, 'image/jpeg');
  fs.writeFileSync(path.join(process.argv[4], 'fps'), '20');
  await waitFor("document.getElementById('note').textContent.includes('20 quadros')");
  await evaluate('performance.clearResourceTimings()');
  await new Promise(resolve => setTimeout(resolve, 1000));
  const fastCount = await evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/_camera/frame.jpg')).length");
  assert.ok(fastCount >= 8 && fastCount <= 24, 'Expected faster polling at 20 FPS, got ' + fastCount);
  const received = await evaluate("Number(document.getElementById('metrics').textContent.match(/Recebidos: ([\\d.]+)/)[1])");
  assert.ok(received > 0 && received < 15, 'Duplicate frame fetches must not count as new frames: ' + received);
  assert.match(await evaluate("document.getElementById('metrics').textContent"), /800 × 450/);
  fs.writeFileSync(path.join(process.argv[4], 'small'), '');
  await waitFor("document.getElementById('frame').naturalWidth === 320 && document.getElementById('metrics').textContent.includes('320 × 180')");
  fs.writeFileSync(path.join(process.argv[4], 'fps'), '2');
  await waitFor("document.getElementById('note').textContent.includes('2 quadros')");
  await evaluate('performance.clearResourceTimings()');
  await new Promise(resolve => setTimeout(resolve, 1200));
  const slowCount = await evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/_camera/frame.jpg')).length");
  assert.ok(slowCount >= 1 && slowCount <= 4, 'Expected slower polling at 2 FPS, got ' + slowCount);
  fs.mkdirSync(process.argv[5], {recursive: true});
  let shot = await call('Page.captureScreenshot', {format: 'png'});
  fs.writeFileSync(path.join(process.argv[5], 'camera-desktop.png'), Buffer.from(shot.data, 'base64'));
  await evaluate("document.getElementById('pause').click()");
  await waitFor("document.getElementById('pause').getAttribute('aria-pressed') === 'true' && document.getElementById('frame').hidden");
  assert.match(await evaluate("document.getElementById('metrics').textContent"), /Recebidos: 0.0 FPS/);
  await new Promise(resolve => setTimeout(resolve, 300));
  const count = await evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/_camera/frame.jpg')).length");
  await new Promise(resolve => setTimeout(resolve, 600));
  assert.equal(await evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/_camera/frame.jpg')).length"), count);
  await evaluate("document.getElementById('pause').click()");
  await waitFor("!document.getElementById('frame').hidden && document.getElementById('status').textContent === 'Ao vivo'");
  fs.writeFileSync(path.join(process.argv[4], 'off'), '');
  await waitFor("document.getElementById('frame').hidden && document.getElementById('status').textContent.includes('Câmera sem imagem')");
  fs.writeFileSync(path.join(process.argv[4], 'on'), '');
  await waitFor("!document.getElementById('frame').hidden && document.getElementById('frame').naturalWidth > 0");
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await evaluate("document.getElementById('language').value='en'; document.getElementById('language').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate('document.documentElement.lang'), 'en');
  assert.equal(await evaluate("document.getElementById('pause').textContent"), 'Pause viewing');
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  shot = await call('Page.captureScreenshot', {format: 'png'});
  fs.writeFileSync(path.join(process.argv[5], 'camera-mobile.png'), Buffer.from(shot.data, 'base64'));
  assert.deepEqual(errors, []);
  console.log('Chrome camera checks passed: unique received FPS ' + received + ', live image resize, live FPS change (20 FPS: ' + fastCount + ' requests/s; 2 FPS: ' + slowCount + ' requests/1.2s), authenticated JPEG, PT/EN, pause/resume, stop/restart, mobile layout. Synthetic frames only.');
  await call('Browser.close');
  socket.close();
})().catch(error => { console.error(error); process.exit(1); });
