(() => {
  'use strict';
  const image = document.getElementById('frame');
  const status = document.getElementById('status');
  const language = document.getElementById('language');
  const pause = document.getElementById('pause');
  const audioButton = document.getElementById('audio');
  const volume = document.getElementById('volume');
  let audioGain;
  try { const saved = Number(localStorage.getItem('serverpy_camera_volume')); if (Number.isInteger(saved) && saved >= 0 && saved <= 100) volume.value = String(saved); } catch (_) {}
  const words = {
    pt: {title: 'Câmera ao vivo', language: 'Idioma', note: 'Até {fps} quadros por segundo. O áudio é opcional e a transmissão é controlada no desktop.',
      audioOn: 'Ativar áudio', audioOff: 'Desativar áudio', volume: 'Volume',
      alt: 'Imagem da câmera', files: 'Abrir arquivos', pause: 'Pausar visualização', resume: 'Retomar visualização',
      connecting: 'Conectando…', live: 'Ao vivo', unavailable: 'Câmera sem imagem. Verifique a transmissão no desktop.',
      auth: 'Acesso negado. Recarregue a página e verifique suas credenciais.', paused: 'Visualização pausada neste navegador.',
      hidden: 'Visualização suspensa enquanto esta aba está oculta.',
      metrics: 'Recebidos: {received} FPS | Publicados: {published} FPS | Imagem: {width} × {height}'},
    en: {title: 'Live camera', language: 'Language', note: 'Up to {fps} frames per second. Audio is optional and streaming is controlled on the desktop.',
      audioOn: 'Enable audio', audioOff: 'Disable audio', volume: 'Volume',
      alt: 'Camera image', files: 'Open files', pause: 'Pause viewing', resume: 'Resume viewing',
      connecting: 'Connecting…', live: 'Live', unavailable: 'No camera image. Check streaming on the desktop.',
      auth: 'Access denied. Reload the page and check your credentials.', paused: 'Viewing paused in this browser.',
      hidden: 'Viewing suspended while this tab is hidden.',
      metrics: 'Received: {received} FPS | Published: {published} FPS | Image: {width} × {height}'}
  };
  let code = navigator.language.startsWith('pt') ? 'pt' : 'en';
  try { const saved = localStorage.getItem('serverpy_camera_language'); if (words[saved]) code = saved; } catch (_) {}
  let state = 'connecting', paused = false, timer, controller, inFlight = false, objectURL, fps = 5;
  let lastFrameID = '', frameSession = '', receivedStart = 0, receivedTimes = [], publishedFPS = 0;
  let audioOn = false, audioAvailable = false, audioCtx, audioTimer, audioAbort, audioBusy = false;
  let audioSession = '', audioOffset = -1, audioNext = 0;
  function receivedFPS() {
    const now = performance.now(), cutoff = Math.max(receivedStart, now - 5000);
    receivedTimes = receivedTimes.filter(value => value > cutoff);
    return now - cutoff >= 500 ? receivedTimes.length * 1000 / (now - cutoff) : 0;
  }
  function setText(element, value) {
    if (element.textContent !== value) element.textContent = value;
  }
  function render() {
    const text = words[code];
    document.documentElement.lang = code;
    document.title = text.title;
    document.getElementById('title').textContent = text.title;
    document.getElementById('language-label').textContent = text.language;
    setText(document.getElementById('note'), text.note.replace('{fps}', String(fps)));
    document.getElementById('files').textContent = text.files;
    image.alt = text.alt;
    language.value = code;
    pause.textContent = text[paused ? 'resume' : 'pause'];
    pause.setAttribute('aria-pressed', String(paused));
    audioButton.hidden = !(audioAvailable || audioOn);
    audioButton.textContent = text[audioOn ? 'audioOff' : 'audioOn'];
    audioButton.setAttribute('aria-pressed', String(audioOn));
    document.getElementById('volume-row').hidden = !audioOn;
    document.getElementById('volume-label').textContent = text.volume;
    setText(status, text[state]);
    const metrics = {received: receivedFPS().toFixed(1), published: publishedFPS.toFixed(1),
      width: image.hidden ? 0 : image.naturalWidth, height: image.hidden ? 0 : image.naturalHeight};
    setText(document.getElementById('metrics'), text.metrics.replace(/\{(\w+)\}/g, (_, key) => metrics[key]));
  }
  function clearImage() {
    image.hidden = true;
    image.removeAttribute('src');
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = undefined;
    receivedTimes = [];
    lastFrameID = frameSession = '';
    publishedFPS = 0;
  }
  function suspend() {
    clearTimeout(timer);
    stopAudioLoop();
    if (controller) controller.abort();
    clearImage();
    state = paused ? 'paused' : 'hidden';
    render();
  }
  function stopAudioLoop() {
    clearTimeout(audioTimer);
    if (audioAbort) audioAbort.abort();
    audioSession = '';
    audioOffset = -1;
    audioNext = 0;
  }
  function playChunk(buffer, rate, channels) {
    const samples = new Int16Array(buffer);
    const frames = samples.length / channels;
    const audioBuffer = audioCtx.createBuffer(channels, frames, rate);
    for (let c = 0; c < channels; c++) {
      const data = audioBuffer.getChannelData(c);
      for (let i = 0; i < frames; i++) data[i] = samples[i * channels + c] / 32768;
    }
    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioGain);
    const now = audioCtx.currentTime;
    if (audioNext < now + 0.05) audioNext = now + 0.15;
    if (audioNext > now + 1.5) return;
    source.start(audioNext);
    audioNext += audioBuffer.duration;
  }
  async function audioPoll() {
    if (!audioOn || paused || document.hidden || audioBusy) return;
    audioBusy = true;
    audioAbort = new AbortController();
    const timeout = setTimeout(() => audioAbort.abort(), 3000);
    let delay = 250;
    try {
      const query = audioSession ? '?session=' + encodeURIComponent(audioSession) + '&after=' + audioOffset : '';
      const response = await fetch('/_camera/audio.pcm' + query, {cache: 'no-store', credentials: 'same-origin', signal: audioAbort.signal});
      if (!response.ok) {
        audioSession = '';
        audioNext = 0;
        delay = 1000;
      } else {
        const buffer = await response.arrayBuffer();
        const rate = Number(response.headers.get('X-Audio-Rate'));
        const channels = Number(response.headers.get('X-Audio-Channels'));
        const offset = Number(response.headers.get('X-Audio-Offset'));
        const session = response.headers.get('X-Audio-Session') || '';
        if (!Number.isInteger(rate) || rate < 8000 || rate > 48000 || (channels !== 1 && channels !== 2) ||
            !Number.isInteger(offset) || !session || buffer.byteLength % (2 * channels)) throw new Error('Invalid audio');
        if (session !== audioSession) audioNext = 0;
        audioSession = session;
        audioOffset = offset;
        if (buffer.byteLength && audioOn) playChunk(buffer, rate, channels);
      }
    } catch (_) {
      if (audioOn) { audioSession = ''; audioNext = 0; delay = 1000; }
    } finally {
      clearTimeout(timeout);
      audioBusy = false;
      if (audioOn && !paused && !document.hidden) audioTimer = setTimeout(audioPoll, delay);
    }
  }
  audioButton.addEventListener('click', () => {
    audioOn = !audioOn;
    if (audioOn) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioGain = audioCtx.createGain();
      audioGain.gain.value = Number(volume.value) / 100;
      audioGain.connect(audioCtx.destination);
      audioCtx.resume();
      audioPoll();
    } else {
      stopAudioLoop();
      if (audioCtx) audioCtx.close();
      audioCtx = undefined;
      audioGain = undefined;
    }
    render();
  });
  volume.addEventListener('input', () => {
    if (audioGain) audioGain.gain.value = Number(volume.value) / 100;
    try { localStorage.setItem('serverpy_camera_volume', volume.value); } catch (_) {}
  });
  async function poll() {
    if (inFlight || paused || document.hidden) return;
    inFlight = true;
    const started = performance.now();
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const response = await fetch('/_camera/frame.jpg', {cache: 'no-store', credentials: 'same-origin', signal: controller.signal});
      const configuredFPS = Number(response.headers.get('X-Camera-FPS'));
      if (Number.isInteger(configuredFPS) && configuredFPS >= 1 && configuredFPS <= 30) fps = configuredFPS;
      audioAvailable = response.headers.get('X-Camera-Audio') === '1';
      if (!response.ok) {
        state = response.status === 401 || response.status === 403 ? 'auth' : 'unavailable';
        clearImage();
      } else {
        const blob = await response.blob();
        if (blob.type !== 'image/jpeg' || blob.size > 8 * 1024 * 1024) throw new Error('Invalid frame');
        if (paused || document.hidden) return;
        const frameID = response.headers.get('X-Camera-Frame-ID') || '';
        const session = frameID.split(':')[0];
        const now = performance.now();
        if (session !== frameSession) {
          frameSession = session;
          receivedStart = now;
          receivedTimes = [];
        }
        if (frameID && frameID !== lastFrameID) {
          receivedTimes.push(now);
          lastFrameID = frameID;
        }
        const rate = Number(response.headers.get('X-Camera-Published-FPS'));
        publishedFPS = Number.isFinite(rate) && rate >= 0 ? rate : 0;
        const previous = objectURL;
        objectURL = URL.createObjectURL(blob);
        image.src = objectURL;
        image.hidden = false;
        if (previous) URL.revokeObjectURL(previous);
        state = 'live';
      }
    } catch (_) {
      if (!paused && !document.hidden) { state = 'unavailable'; clearImage(); }
    } finally {
      clearTimeout(timeout);
      inFlight = false;
      controller = undefined;
      render();
      if (!paused && !document.hidden) {
        const interval = state === 'auth' ? 2000 : state === 'unavailable' ? 1000 : 1000 / fps;
        timer = setTimeout(poll, Math.max(0, interval - (performance.now() - started)));
      }
    }
  }
  image.addEventListener('error', () => { clearImage(); state = 'unavailable'; render(); });
  image.addEventListener('load', render);
  language.addEventListener('change', () => {
    code = language.value;
    try { localStorage.setItem('serverpy_camera_language', code); } catch (_) {}
    render();
  });
  pause.addEventListener('click', () => {
    paused = !paused;
    if (paused) suspend(); else { state = 'connecting'; render(); poll(); audioPoll(); }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) suspend(); else if (!paused) { state = 'connecting'; render(); poll(); audioPoll(); }
  });
  window.addEventListener('pagehide', suspend);
  render();
  poll();
})();
