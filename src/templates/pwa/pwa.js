(() => {
    const button = document.getElementById('btn-install');
    const status = document.getElementById('connection-status');
    let installPrompt = null;
    const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    const updateConnection = () => { status.hidden = navigator.onLine; };
    updateConnection();
    window.addEventListener('online', updateConnection);
    window.addEventListener('offline', updateConnection);
    window.addEventListener('beforeinstallprompt', event => {
        event.preventDefault();
        installPrompt = event;
        button.hidden = !!standalone();
    });
    window.addEventListener('appinstalled', () => {
        installPrompt = null;
        button.hidden = true;
    });
    button.addEventListener('click', async () => {
        if (!installPrompt) return;
        button.disabled = true;
        try {
            await installPrompt.prompt();
            await installPrompt.userChoice;
        } catch (error) {
            console.warn('ServerPy install prompt:', error);
        } finally {
            installPrompt = null;
            button.disabled = false;
            button.hidden = true;
        }
    });
    if (window.isSecureContext && 'serviceWorker' in navigator) {
        navigator.serviceWorker.register('/_serverpy/pwa/sw.js', {scope: '/', updateViaCache: 'none'})
            .catch(error => console.warn('ServerPy PWA:', error));
    }
})();
