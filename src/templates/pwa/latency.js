(() => {
    const footer = document.getElementById('server-status');
    const current = document.getElementById('server-latency');
    const average = document.getElementById('server-latency-average');
    const samples = [];
    let latest = null;
    let message = 'Measuring...';
    let timer;
    let controller;
    let running = false;
    let stopped = false;
    const translate = (text, values) => typeof t === 'function' ? t(text, values) : text;

    function render() {
        current.textContent = latest === null ? translate(message) : `Ping ${Math.round(latest)} ms`;
        average.textContent = samples.length ? `${Math.round(samples.reduce((sum, value) => sum + value, 0) / samples.length)} ms` : '—';
        footer.title = translate('HTTP round trip. Average of the last {count} measurements; checked every 5 seconds.', {count: samples.length});
    }

    async function measure() {
        clearTimeout(timer);
        if (running || stopped || document.hidden) return;
        running = true;
        controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            if (!navigator.onLine) throw new Error('Server unavailable');
            const started = performance.now();
            const response = await fetch((document.body.dataset.urlPrefix || '') + '/api/ping', {cache: 'no-store', signal: controller.signal});
            if (!response.ok) {
                throw new Error(response.status === 401 ? 'Authentication required' : response.status === 429 ? 'Too many requests' : 'Server unavailable');
            }
            if ((await response.json()).ok !== true) throw new Error('Server unavailable');
            latest = performance.now() - started;
            samples.push(latest);
            if (samples.length > 10) samples.shift();
            footer.dataset.state = latest > 250 ? 'slow' : 'online';
        } catch (error) {
            latest = null;
            samples.length = 0;
            message = ['Authentication required', 'Too many requests'].includes(error.message) ? error.message : 'Server unavailable';
            footer.dataset.state = 'offline';
        } finally {
            clearTimeout(timeout);
            running = false;
            render();
            if (!stopped && !document.hidden) timer = setTimeout(measure, 5000);
        }
    }
    window.addEventListener('serverpy:languagechange', render);
    window.addEventListener('online', measure);
    window.addEventListener('offline', () => {
        if (running) controller.abort();
        else measure();
    });
    document.addEventListener('visibilitychange', () => {
        clearTimeout(timer);
        if (!document.hidden) measure();
    });
    window.addEventListener('pagehide', () => {
        stopped = true;
        clearTimeout(timer);
        controller?.abort();
    });
    window.addEventListener('pageshow', event => {
        if (event.persisted) { stopped = false; measure(); }
    });
    render();
    measure();
})();
