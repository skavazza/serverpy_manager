// Run against an isolated server and Chrome debugging session:
// node tests/web_interface_smoke.cjs <debugging-port> <server-url>
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
    const targets = await (await fetch(`http://127.0.0.1:${process.argv[2]}/json/list`)).json();
    const socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise(resolve => socket.addEventListener('open', resolve, {once: true}));
    let id = 0;
    const pending = new Map();
    const mountPrefix = new URL(process.argv[3]).pathname.replace(/\/$/, '');
    socket.addEventListener('message', event => {
        const data = JSON.parse(event.data);
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
        for (let attempt = 0; attempt < 80; attempt++) {
            try { if (await evaluate(expression)) return; } catch {}
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        throw Error('Timeout: ' + expression);
    }
    await call('Page.navigate', {url: process.argv[3]});
    await waitFor("typeof sortFiles === 'function' && document.getElementById('fileGrid')");
    await waitFor("document.getElementById('server-status').dataset.state === 'online'");
    assert.match(await evaluate("document.getElementById('server-latency').textContent"), /^Ping \d+ ms$/);
    assert.match(await evaluate("document.getElementById('server-latency-average').textContent"), /^\d+ ms$/);
    await evaluate("setLanguage('pt'); setView('list'); sortFiles('size')");
    assert.match(await evaluate("document.getElementById('server-status').textContent"), /Média/);
    assert.match(await evaluate("document.getElementById('server-status').title"), /Tempo de ida e volta HTTP/);
    assert.equal(await evaluate("document.getElementById('btn-preview').textContent"), 'PRÉ-VISUALIZAR');
    assert.equal(await evaluate("[...document.querySelectorAll('.card[data-directory=false]')].map(card => Number(card.dataset.size)).every((size, i, sizes) => i === 0 || sizes[i-1] <= size)"), true);
    await evaluate("toggleSortDirection(); filterFiles('sample')");
    assert.equal(await evaluate("getComputedStyle(document.querySelector('.card[data-name=\"sample.txt\"]')).display"), 'flex');
    assert.equal(await evaluate("getComputedStyle(document.querySelector('.card[data-name=\"sample.txt\"] .modified')).display"), 'block');
    await evaluate("filterFiles(''); toggleSidebar(true)");
    await waitFor("document.querySelectorAll('#folder-tree a').length >= 3");

    // Upload real File objects and inspect both success and conflict feedback.
    assert.deepEqual(await evaluate("uploadFiles([new File(['uploaded'], 'ação # & 100%20.txt')])"), undefined);
    assert.equal(await evaluate("[...document.querySelectorAll('.card[data-name]')].some(card => card.dataset.name === 'ação # & 100%20.txt')"), true);
    await evaluate("uploadFiles([new File(['overwrite'], 'ação # & 100%20.txt')])");
    assert.match(await evaluate("document.getElementById('operation-errors').textContent"), /Já existe/);
    assert.equal(await evaluate("fetch(fileUrl('/ação # & 100%20.txt')).then(response => response.text())"), 'uploaded');
    assert.deepEqual(await evaluate('transfers.map(item => item.state)'), ['Completed', 'Failed']);
    assert.equal(await evaluate("document.getElementById('transfers-dialog').open"), true);
    assert.match(await evaluate("document.getElementById('transfers-list').textContent"), /Concluída/);
    await evaluate("document.getElementById('transfers-dialog').close()");

    // A real throttled upload can be cancelled; queued files can be cancelled and retried.
    await call('Network.enable');
    await call('Network.setBypassServiceWorker', {bypass:true});
    await call('Network.emulateNetworkConditions', {offline:false, latency:10, downloadThroughput:-1, uploadThroughput:65536});
    await evaluate("{window.uploadBatch = uploadTo([new File([new Uint8Array(4 * 1024 * 1024)], 'cancel-large.bin'), new File(['queued'], 'queued-upload.txt')], '/'); void 0;}");
    await waitFor("transfers.find(item => item.name === 'cancel-large.bin').done > 0");
    await evaluate("cancelUpload(transfers.find(item => item.name === 'queued-upload.txt')); cancelUpload(transfers.find(item => item.name === 'cancel-large.bin'))");
    await call('Network.emulateNetworkConditions', {offline:false, latency:0, downloadThroughput:-1, uploadThroughput:-1});
    await evaluate('window.uploadBatch');
    assert.deepEqual(await evaluate("transfers.slice(-2).map(item => item.state)"), ['Cancelled', 'Cancelled']);
    assert.equal(await evaluate("fetch(fileUrl('/cancel-large.bin')).then(response => response.status)"), 404);
    assert.equal(await evaluate("fetch(fileUrl('/queued-upload.txt')).then(response => response.status)"), 404);
    await evaluate("retryUpload(transfers.find(item => item.name === 'queued-upload.txt'))");
    assert.equal(await evaluate("fetch(fileUrl('/queued-upload.txt')).then(response => response.text())"), 'queued');
    assert.equal(await evaluate("transfers.find(item => item.name === 'queued-upload.txt').state"), 'Completed');
    await screenshot('transfer-center');
    await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
    await call('Emulation.setTouchEmulationEnabled', {enabled:true, maxTouchPoints:1});
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
    assert.equal(await evaluate("document.getElementById('transfers-dialog').scrollWidth <= document.getElementById('transfers-dialog').clientWidth"), true);
    await screenshot('transfer-center-mobile');
    await call('Emulation.setDeviceMetricsOverride', {width:1440, height:900, deviceScaleFactor:1, mobile:false});
    await call('Emulation.setTouchEmulationEnabled', {enabled:false});
    await evaluate("clearTransfers(); document.getElementById('transfers-dialog').close()");
    await call('Network.setBypassServiceWorker', {bypass:false});

    // A partial cut retains failed items, and refresh does not lose the user's view.
    await evaluate("setClipboard(['/sample.txt', '/missing.txt'], 'cut'); history.replaceState(null, '', (document.body.dataset.urlPrefix || '') + '/docs/'); pasteClipboard()");
    assert.deepEqual(await evaluate('getClipboard().items'), ['/missing.txt']);
    assert.equal(await evaluate("document.getElementById('fileGrid').classList.contains('list-view')"), true);
    assert.match(await evaluate("document.getElementById('operation-errors').textContent"), /missing.txt/);
    await evaluate("history.replaceState(null, '', (document.body.dataset.urlPrefix || '') + '/'); refreshListing()");

    // Drag a local file onto the page, then move it into a folder through the sidebar.
    await evaluate("{const transfer = new DataTransfer(); transfer.items.add(new File(['dropped'], 'drop.txt')); document.querySelector('.content').dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}))}");
    await waitFor("!operationBusy && [...document.querySelectorAll('.card[data-name]')].some(card => card.dataset.name === 'drop.txt')");
    await evaluate("document.getElementById('transfers-dialog').close()");
    await waitFor("[...document.querySelectorAll('#folder-tree a')].some(link => link.textContent === 'docs')");
    await evaluate("{window.confirm = () => true; const transfer = new DataTransfer(); document.querySelector('.card[data-name=\"drop.txt\"]').dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:transfer})); [...document.querySelectorAll('#folder-tree a')].find(link => link.textContent === 'docs').dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}))}");
    await waitFor('!operationBusy');
    assert.equal(await evaluate("fetch(fileUrl('/docs/drop.txt')).then(response => response.text())"), 'dropped');

    // Real image preview, media controls, PDF frame and cleanup on close.
    await evaluate("openPreview(document.querySelector('.card[data-name=\"image.png\"]'))");
    await waitFor("document.querySelector('#preview-content img')?.naturalWidth > 0");
    assert.equal(await evaluate("document.getElementById('preview-dialog').open"), true);
    await evaluate("document.getElementById('preview-dialog').close()");
    await waitFor("document.getElementById('preview-content').children.length === 0");
    assert.deepEqual(await evaluate("['sound.wav', 'video.mp4', 'document.pdf'].map(name => {openPreview(document.querySelector('.card[data-name=\"' + name + '\"]')); const element = document.getElementById('preview-content').firstElementChild; const result = {tag:element.tagName, controls:element.controls || false}; document.getElementById('preview-dialog').close(); return result;})"), [{tag:'AUDIO', controls:true}, {tag:'VIDEO', controls:true}, {tag:'IFRAME', controls:false}]);
    await evaluate("sortFiles('modified')");
    await evaluate("document.documentElement.dataset.theme = 'light'; toggleTheme(); toggleFavorite(); document.querySelector('.search-input').value = 'deep-report'; document.getElementById('search-recursive').checked = true; handleSearch('deep-report')");
    await waitFor("document.querySelectorAll('.search-result').length === 1");
    assert.equal(await evaluate("document.querySelector('.search-result small').textContent"), '/docs/nested/deep-report.txt');
    assert.equal(await evaluate("document.querySelector('.search-result a:last-child').getAttribute('href')"), mountPrefix + '/docs/nested/');
    await evaluate("document.querySelector('.search-input').value = ''; handleSearch(''); selectedFiles = new Set(['ação # & 100%20.txt']); updateToolbar(); deleteSelected()");
    await waitFor('!operationBusy');
    await evaluate("openRecovery('trash')");
    await waitFor("document.querySelectorAll('.recovery-row').length === 1");
    assert.equal(await evaluate("document.querySelector('.recovery-row strong').textContent"), 'ação # & 100%20.txt');
    await evaluate("document.querySelector('.recovery-row button').click()");
    await waitFor("!document.querySelector('.recovery-row') && [...document.querySelectorAll('.card[data-name]')].some(card => card.dataset.name === 'ação # & 100%20.txt')");
    await evaluate("document.getElementById('recovery-dialog').close(); openRecovery('moves')");
    await waitFor("document.querySelectorAll('.recovery-row').length === 2");
    await evaluate("document.querySelector('.recovery-row button').click()");
    await waitFor("document.querySelectorAll('.recovery-row').length === 1 && document.querySelector('.card[data-name=\"drop.txt\"]')");
    await evaluate("document.getElementById('recovery-dialog').close()");
    await evaluate('window.explorerReady = false');
    await call('Page.reload');
    await waitFor("window.explorerReady && document.getElementById('fileGrid') && document.getElementById('sort-select').value === 'modified'");
    assert.equal(await evaluate("document.getElementById('fileGrid').classList.contains('list-view')"), true);
    assert.equal(await evaluate("document.getElementById('folder-sidebar').hidden"), false);
    assert.equal(await evaluate("document.documentElement.dataset.theme"), 'dark');
    assert.equal(await evaluate("document.querySelectorAll('#favorite-list a').length"), 1);
    assert.equal(await evaluate("document.getElementById('btn-favorite').getAttribute('aria-pressed')"), 'true');
    async function screenshot(name) {
        if (!process.argv[4]) return;
        await new Promise(resolve => setTimeout(resolve, 200));
        fs.mkdirSync(process.argv[4], {recursive:true});
        const result = await call('Page.captureScreenshot', {format:'png', captureBeyondViewport:false});
        fs.writeFileSync(path.join(process.argv[4], name + '.png'), Buffer.from(result.data, 'base64'));
    }
    await call('Emulation.setDeviceMetricsOverride', {width:1440, height:900, deviceScaleFactor:1, mobile:false});
    await evaluate("document.getElementById('operation-panel').hidden = true; setClipboard([], null); setView('grid'); sortDirection = 'asc'; sortFiles('name'); toggleSidebar(true)");
    await screenshot('explorer-dark');
    await evaluate('toggleTheme()');
    await screenshot('explorer-light');
    await call('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
    await call('Emulation.setTouchEmulationEnabled', {enabled:true, maxTouchPoints:1});
    assert.equal(await evaluate('navigator.maxTouchPoints'), 1);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
    assert.equal(await evaluate("{const rect = document.getElementById('server-status').getBoundingClientRect(); rect.left === 0 && Math.abs(rect.bottom - innerHeight) <= 1}"), true);
    await screenshot('explorer-mobile');
    // Exercise browser-generated touch/click events, not only a narrow viewport.
    async function tap(selector) {
        const point = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return {x:r.x+r.width/2, y:r.y+r.height/2}; })()`);
        await call('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[point]});
        await call('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
    }
    await tap('#folder-sidebar .sidebar-action');
    await waitFor("document.getElementById('folder-sidebar').hidden");
    await tap('#btn-sidebar');
    await waitFor("!document.getElementById('folder-sidebar').hidden");
    await evaluate("toggleSidebar(false); setView('list')");
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
    // Validate the worker in a real browser and preserve live server responses.
    await waitFor('navigator.serviceWorker.controller !== null');
    const manifest = await call('Page.getAppManifest');
    assert.deepEqual(manifest.errors, []);
    assert.equal(JSON.parse(manifest.data).display, 'standalone');
    const installability = await call('Page.getInstallabilityErrors');
    assert.deepEqual(installability.installabilityErrors, []);
    assert.deepEqual(await evaluate("caches.open('serverpy-pwa-v1').then(cache => cache.keys()).then(keys => keys.map(key => new URL(key.url).pathname))"), ['/_serverpy/pwa/offline.html']);
    await evaluate("{const event = new Event('beforeinstallprompt'); event.prompt = async () => {}; event.userChoice = Promise.resolve({outcome:'dismissed'}); window.dispatchEvent(event)}");
    assert.equal(await evaluate("document.getElementById('btn-install').hidden"), false);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
    await evaluate("document.getElementById('btn-install').click()");
    await waitFor("document.getElementById('btn-install').hidden");
    if (process.argv[7]) {
        const links = JSON.parse(fs.readFileSync(process.argv[7], 'utf8'));
        fs.mkdirSync(links.directory, {recursive: true});
        await call('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: links.directory});
        await call('Page.navigate', {url: links.protected});
        await waitFor("document.querySelector('form input[type=password]')");
        assert.equal(await evaluate("document.querySelector('form').method"), 'post');
        assert.equal(await evaluate("document.querySelector('input[type=password]').value"), '');
        await screenshot('protected-link');
        await evaluate("document.querySelector('input[type=password]').value = 'wrong'; document.querySelector('form').requestSubmit()");
        await waitFor("document.querySelector('.error')?.textContent.trim().length > 0");
        assert.match(await evaluate("document.querySelector('.error').textContent"), /Incorrect link password|Senha do link incorreta/);
        await evaluate(`document.querySelector('input[type=password]').value = ${JSON.stringify(links.password)}; document.querySelector('form').requestSubmit()`);
        const destination = path.join(links.directory, 'link-only.txt');
        for (let attempt = 0; attempt < 80 && !fs.existsSync(destination); attempt++) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        assert.equal(fs.readFileSync(destination, 'utf8'), 'temporary link download');
        await call('Page.navigate', {url: process.argv[3]});
        await waitFor("window.explorerReady && document.getElementById('server-status').dataset.state === 'online'");
        assert.equal(await evaluate(`fetch(${JSON.stringify(links.plain)}).then(response => response.text())`), 'temporary link download');
    }
    async function toggleTestServer(action, acknowledgement) {
        fs.writeFileSync(path.join(process.argv[6], action), '');
        for (let attempt = 0; attempt < 100; attempt++) {
            if (fs.existsSync(path.join(process.argv[6], acknowledgement))) return;
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        throw Error('Server control timeout: ' + action);
    }
    // Stop the actual test server: target-only offline emulation does not stop worker fetches.
    await toggleTestServer('stop', 'stopped');
    await evaluate("window.dispatchEvent(new Event('online'))");
    await waitFor("document.getElementById('server-status').dataset.state === 'offline'");
    assert.equal(await evaluate("document.getElementById('server-latency').textContent"), 'Servidor indisponível');
    assert.equal(await evaluate("document.getElementById('server-latency-average').textContent"), '—');
    await call('Network.enable');
    await call('Network.emulateNetworkConditions', {offline:true, latency:0, downloadThroughput:-1, uploadThroughput:-1});
    await call('Page.navigate', {url:new URL('docs/', process.argv[3]).href});
    await waitFor("document.getElementById('retry') && !document.getElementById('fileGrid')");
    assert.equal(await evaluate("document.getElementById('title').textContent"), 'Servidor indisponível');
    assert.equal(await evaluate("fetch('/api/search?q=report').then(() => false).catch(() => true)"), true);
    assert.equal(await evaluate("fetch('/docs/drop.txt').then(() => false).catch(() => true)"), true);
    await toggleTestServer('start', 'started');
    await call('Network.emulateNetworkConditions', {offline:false, latency:0, downloadThroughput:-1, uploadThroughput:-1});
    await evaluate("document.getElementById('retry').click()");
    await waitFor("window.explorerReady && document.getElementById('fileGrid')");
    await waitFor("document.getElementById('server-status').dataset.state === 'online'");
    if (process.argv[5]) {
        await call('Page.navigate', {url:process.argv[5]});
        await waitFor("typeof updateToolbar === 'function' && document.body.dataset.allowMod === 'false'");
        await evaluate("selectedFiles = new Set(['image.png']); updateToolbar()");
        assert.equal(await evaluate("document.getElementById('btn-delete').disabled"), true);
        assert.equal(await evaluate("document.getElementById('btn-preview').disabled"), false);
        assert.equal(await evaluate("fetch(fileUrl('/image.png'), {method:'DELETE'}).then(response => response.status)"), 405);
        await evaluate("document.querySelector('.search-input').value = 'deep-report'; document.getElementById('search-recursive').checked = true; handleSearch('deep-report')");
        await waitFor("document.querySelectorAll('.search-result').length === 1");
    }
    console.log('Chrome checks passed: transfer queue, cancellation, retry, file operations, previews, search, recovery, preferences, desktop 1440px, mobile 390px with touch events, PWA, temporary links, password downloads, live latency footer, disconnect and reconnection.');
    await call('Browser.close');
    socket.close();
})().catch(error => { console.error(error); process.exit(1); });
