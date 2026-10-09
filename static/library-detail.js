(() => {
  const id = document.body.dataset.adId, endpoint = '/api/library/ads/' + encodeURIComponent(id);
  const status = document.querySelector('#detail-status'), video = document.querySelector('#detail-video');
  let dirty = false, editorVersion = null, layer = 'speech', versions = [], selectedVersion = null, currentItem = null, loading = false, previewLike = null;
  document.querySelector('#transcript-form').addEventListener('input', () => { dirty = true; });
  document.querySelector('#export-ad').href = endpoint + '/export';
  function node(tag, text, className) { const item = document.createElement(tag); if (text) item.textContent = text; if (className) item.className = className; return item; }
  function field(parent, label, input) {
    const wrapper = node('label', label); wrapper.append(input); parent.append(wrapper); return input;
  }
  function addRow(channel, data = {}) {
    const row = node('div', '', 'transcript-row'), grid = node('div', '', 'field-grid');
    for (const [key, label] of [['start', 'Inicio (s)'], ['end', 'Fin (s)']]) {
      const input = node('input'); input.type = 'number'; input.step = '0.01'; input.min = '0'; input.required = true; input.dataset.field = key; input.value = data[key] ?? (key === 'start' ? 0 : 5); field(grid, label, input);
    }
    if (channel === 'speech') {
      const speaker = node('input'); speaker.required = true; speaker.maxLength = 80; speaker.dataset.field = 'speaker'; speaker.value = data.speaker || 'Persona 1'; field(grid, 'Hablante', speaker);
      const role = node('select'); role.dataset.field = 'role';
      for (const [value, text] of [['unknown', 'Sin identificar'], ['on_camera', 'Voz en cámara'], ['voiceover', 'VoiceOver']]) { const option = node('option', text); option.value = value; role.append(option); }
      role.value = data.role || 'unknown'; field(grid, 'Tipo de voz', role);
    }
    const textField = channel === 'speech' ? 'text' : 'description', textarea = node('textarea'); textarea.rows = 3; textarea.required = true; textarea.maxLength = 6000; textarea.dataset.field = textField; textarea.value = data[textField] || '';
    row.append(grid); field(row, channel === 'speech' ? 'Lo que dice' : 'Lo que ocurre en la escena', textarea);
    const actions = node('div', '', 'segment-actions'), seek = node('button', 'Ver este momento', 'text-button'), remove = node('button', 'Eliminar', 'text-button'); seek.type = remove.type = 'button';
    seek.addEventListener('click', () => { if (!video.hidden) { video.currentTime = Number(row.querySelector('[data-field=start]').value); video.play().catch(() => {}); } else status.textContent = 'Todavía no hay un video disponible para reproducir.'; });
    remove.addEventListener('click', () => row.remove()); actions.append(seek, remove); row.append(actions);
    document.querySelector(channel === 'speech' ? '#speech-rows' : '#scene-rows').append(row);
  }
  document.querySelector('#add-speech').addEventListener('click', () => addRow('speech'));
  document.querySelector('#add-scene').addEventListener('click', () => addRow('scenes'));
  const kinds = {download: 'Descarga', drive_video: 'Video en Drive', drive_transcript: 'Transcripción en Drive', transcribe: 'Transcripción automática'};
  const states = {pending: 'En cola', running: 'Procesando', done: 'Completada', blocked: 'Requiere configuración o revisión', failed: 'Error; puedes reintentar'};
  async function load(initial = false) {
    if (loading) return;
    loading = true;
    try {
      const item = await LibraryApi.request(endpoint);
      currentItem = item;
      const history = await LibraryApi.request(endpoint + '/transcripts');
      versions = history.items;
      const selector = document.querySelector('#transcript-version'); selector.replaceChildren();
      for (const transcript of versions) {
        const option = node('option', `Versión ${transcript.version} · ${transcript.origin.startsWith('hf:') ? 'IA · Hugging Face' : transcript.origin.startsWith('kie:') ? 'IA · Kie / Gemini' : 'Revisión manual'}${transcript.reviewed ? ' · Revisada' : ''}`); option.value = transcript.id; selector.append(option);
      }
      if (!versions.length) selector.append(node('option', 'Esperando transcripción'));
      if (!versions.some(version => version.id === selectedVersion)) selectedVersion = versions[0]?.id || null;
      selector.value = selectedVersion || '';
      renderTimeline();
      if (initial || previewLike !== item.liked) { AdResults.render(document.querySelector('#ad-preview'), [item.raw], item.platform, {entries: [item]}); previewLike = item.liked; }
      const assets = document.querySelector('#asset-links'); assets.replaceChildren();
      for (const [index, asset] of item.assets.entries()) {
        const paragraph = node('p'), label = node('span', `Video ${index + 1}: `); paragraph.append(label);
        if (asset.available || asset.driveUrl) {
          const download = node('a', '↓ Descargar video', 'outline'); download.href = '/api/library/assets/' + asset.id + '/media?download=1'; paragraph.append(download);
          if ((initial || video.hidden || asset.driveUrl && !video.src.includes('/api/library/assets/')) && index === 0) { video.src = '/api/library/assets/' + asset.id + '/media'; video.hidden = false; }
        } else paragraph.append(node('span', asset.downloaded ? 'Descargado para análisis · pendiente de Drive' : 'Descarga pendiente'));
        if (asset.driveUrl) { const link = node('a', 'Abrir en Drive →', 'outline'); link.href = AdResults.safeUrl(asset.driveUrl); link.target = '_blank'; link.rel = 'noopener noreferrer'; paragraph.append(link); }
        assets.append(paragraph);
      }
      if (!item.assets.length) assets.textContent = item.kind === 'organic' ? 'Enlace orgánico guardado. Falta integrar su extracción de video.' : 'Este registro no incluye un enlace directo de video. Los previews externos no permiten descargar el archivo.';
      if (initial) selectVideo(versions.find(version => version.id === selectedVersion)?.sourceAssetId);
      if (initial && video.hidden) { const original = AdResults.normalize(item.raw, item.platform).videoUrl; if (original) { video.src = original; video.hidden = false; } }
      const jobs = document.querySelector('#job-list'); jobs.replaceChildren();
      for (const job of item.jobs) jobs.append(node('li', `${kinds[job.kind] || job.kind}: ${states[job.status] || job.status}${job.error ? ' · ' + job.error : ''}`));
      if (!item.jobs.length) jobs.append(node('li', 'Sin tareas de archivos en cola.'));
      status.textContent = item.transcript ? `Transcripción versión ${item.transcript.version} · ${item.transcript.reviewed ? 'Revisada' : 'Pendiente de revisión'}.` : 'Transcripción automática pendiente. Revisa el servicio de procesamiento y la configuración del proveedor de transcripción.';
      document.querySelector('#editing-version').textContent = item.transcript ? `Corrección de la última versión guardada (${item.transcript.version}). El selector superior permite consultar las anteriores.` : 'La transcripción aparecerá automáticamente; las correcciones son opcionales.';
      if (!dirty && editorVersion !== (item.transcript?.version || 0)) {
        document.querySelector('#speech-rows').replaceChildren(); document.querySelector('#scene-rows').replaceChildren();
        editorVersion = item.transcript?.version || 0;
        for (const segment of item.transcript?.speech || []) addRow('speech', segment);
        for (const segment of item.transcript?.scenes || []) addRow('scenes', segment);
        document.querySelector('#transcript-reviewed').checked = Boolean(item.transcript?.reviewed);
      }
    } catch (error) { status.textContent = error.message; }
    finally { loading = false; }
  }
  document.querySelector('#refresh-detail').addEventListener('click', () => load());
  document.querySelector('#retry-jobs').addEventListener('click', async event => {
    event.target.disabled = true;
    try { await LibraryApi.request(endpoint + '/retry', {}); await load(); status.textContent = 'Tareas pendientes reenviadas a la cola. Se ejecutarán cuando el servicio de procesamiento esté activo.'; }
    catch (error) { status.textContent = error.message; } finally { event.target.disabled = false; }
  });
  document.querySelector('#transcript-form').addEventListener('submit', async event => {
    event.preventDefault(); const button = event.target.querySelector('button.primary'); button.disabled = true;
    const payload = {reviewed: document.querySelector('#transcript-reviewed').checked, sourceAssetId: currentItem?.transcript?.sourceAssetId || null};
    for (const [channel, selector] of [['speech', '#speech-rows'], ['scenes', '#scene-rows']]) {
      payload[channel] = [...document.querySelector(selector).children].map(row => Object.fromEntries([...row.querySelectorAll('[data-field]')].map(input => [input.dataset.field, ['start','end'].includes(input.dataset.field) ? Number(input.value) : input.value])));
    }
    try { const saved = await LibraryApi.request(endpoint + '/transcript', payload); document.querySelector('#transcript-status').textContent = `Versión ${saved.transcript.version} guardada en Supabase. Su archivo se subirá a Drive cuando el procesamiento y Drive estén conectados.`; dirty = false; selectedVersion = saved.transcript.id; await load(); }
    catch (error) { document.querySelector('#transcript-status').textContent = error.message; }
    finally { button.disabled = false; }
  });
  video.addEventListener('error', () => { status.textContent = 'El video aún no está disponible en este servidor o su enlace expiró. Actualiza el estado cuando termine la subida a Drive.'; });
  function time(seconds) { const minutes = Math.floor(seconds / 60); return `${String(minutes).padStart(2,'0')}:${(seconds % 60).toFixed(1).padStart(4,'0')}`; }
  function selectVideo(assetId) {
    const asset = currentItem?.assets.find(item => item.id === assetId);
    if (asset) { const url = asset.available || asset.driveUrl ? '/api/library/assets/' + asset.id + '/media' : AdResults.safeUrl(asset.sourceUrl); if (url) { if (!video.src.endsWith(url)) video.src = url; video.hidden = false; } }
  }
  function renderTimeline() {
    const timeline = document.querySelector('#transcript-timeline'); timeline.replaceChildren();
    const transcript = versions.find(version => version.id === selectedVersion);
    const automaticStatus = document.querySelector('#automatic-status');
    if (!transcript) {
      const jobs = currentItem?.jobs.filter(job => ['download','transcribe'].includes(job.kind)) || [];
      const issue = jobs.find(job => ['blocked','failed'].includes(job.status));
      automaticStatus.textContent = issue?.error || 'La transcripción aparecerá aquí automáticamente cuando termine el análisis. No necesitas escribirla.';
      timeline.append(node('p', 'Aún no hay segmentos disponibles.', 'hint')); return;
    }
    automaticStatus.textContent = transcript.origin.startsWith('hf:') || transcript.origin.startsWith('kie:') ? 'Transcripción automática · ' + (transcript.origin.startsWith('hf:') ? 'Hugging Face · ' : 'Kie / Gemini · ') + (transcript.reviewed ? 'Revisada por el equipo' : 'Pendiente de revisión') : 'Transcripción revisada o escrita por el equipo.';
    const segments = transcript[layer] || [];
    if (!segments.length) timeline.append(node('p', layer === 'speech' ? 'No se detectó voz en esta versión.' : 'No hay escenas en esta versión.', 'hint'));
    for (const segment of segments) {
      const row = node('article', '', 'timeline-segment'), seek = node('button', `${time(segment.start)} → ${time(segment.end)}`, 'timeline-time'); seek.type = 'button';
      seek.addEventListener('click', () => { selectVideo(transcript.sourceAssetId); if(!video.hidden) { video.currentTime = segment.start; video.play().catch(()=>{}); } });
      row.append(seek);
      if (layer === 'speech') row.append(node('span', `${segment.speaker} · ${segment.role === 'voiceover' ? 'VoiceOver' : segment.role === 'on_camera' ? 'En cámara' : 'Voz sin identificar'}`, 'tag'));
      row.append(node('p', layer === 'speech' ? segment.text : segment.description)); timeline.append(row);
    }
  }
  document.querySelector('#transcript-version').addEventListener('change', event => { selectedVersion = event.target.value; const transcript = versions.find(version => version.id === selectedVersion); selectVideo(transcript?.sourceAssetId); renderTimeline(); });
  document.querySelectorAll('[data-transcript-layer]').forEach(button => button.addEventListener('click', () => { layer = button.dataset.transcriptLayer; document.querySelectorAll('[data-transcript-layer]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); renderTimeline(); }));
  const poll = setInterval(() => { if (!document.hidden) load(); }, 5000);
  window.addEventListener('pagehide', () => clearInterval(poll));
  load(true);
})();
