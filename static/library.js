(() => {
  const status = document.querySelector('#library-status');
  let liked = false, offset = 0, items = [], loading = false;
  async function load(reset = true) {
    if (loading) return;
    loading = true;
    try {
      const data = await LibraryApi.request(`/api/library?liked=${liked ? 1 : 0}&offset=${reset ? 0 : offset}&limit=50`);
      items = reset ? data.items : items.concat(data.items); offset = items.length;
      AdResults.render(document.querySelector('#library-results'), items.map(item => item.raw), 'facebook', {entries: items});
      if (!items.length) document.querySelector('#library-results').textContent = 'Todavía no hay referencias guardadas en esta vista.';
      document.querySelector('#load-more').hidden = data.items.length < 50;
    } catch (error) { status.textContent = error.message; }
    finally { loading = false; }
  }
  async function runs() {
    try {
      const data = await LibraryApi.request('/api/library/runs'); const list = document.querySelector('#import-runs'); list.replaceChildren();
      const states = {pending: 'En cola para procesamiento automático', running: 'Importando', done: 'Importación completa', blocked: 'Bloqueada', failed: 'Error'};
      for (const run of data.items) {
        const row = document.createElement('li'); row.textContent = `${run.platform} · ${run.id} · ${states[run.status] || run.status}${run.error ? ' · ' + run.error : ''}`;
        if (['blocked','failed'].includes(run.status)) {
          const retry = document.createElement('button'); retry.textContent = 'Reintentar guardado'; retry.className = 'text-button';
          retry.addEventListener('click', async () => { retry.disabled = true; try { await LibraryApi.request('/api/library/runs/' + encodeURIComponent(run.id) + '/retry', {}); await runs(); } catch(error) { status.textContent = error.message; retry.disabled = false; } }); row.append(retry);
        }
        list.append(row);
      }
      if (!data.items.length) list.textContent = 'Todavía no hay búsquedas registradas en Supabase.';
    } catch(error) { status.textContent = error.message; }
  }
  document.querySelector('#refresh-library').addEventListener('click', () => { load(); runs(); });
  runs();
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    if (loading) return;
    liked = button.dataset.filter === 'liked';
    document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); load();
  }));
  document.querySelector('#load-more').addEventListener('click', () => load(false));
  document.querySelector('#connect-drive').addEventListener('click', async event => {
    event.target.disabled = true;
    try { const data = await LibraryApi.request('/api/drive/connect', {}); location.assign(data.url); }
    catch (error) { status.textContent = error.message; event.target.disabled = false; }
  });
  document.querySelector('#reference-form').addEventListener('submit', async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try {
      await LibraryApi.request('/api/library/references', {url: document.querySelector('#reference-url').value, title: document.querySelector('#reference-title').value});
      document.querySelector('#reference-status').textContent = 'Referencia guardada en Supabase.'; event.target.reset(); await load();
    } catch (error) { document.querySelector('#reference-status').textContent = error.message; }
    finally { button.disabled = false; }
  });
  LibraryApi.request('/api/library/config').then(config => {
    status.textContent = !config.databaseConfigured ? 'Falta configurar DATABASE_URL de Supabase en Render. No se guardan datos de forma permanente hasta conectarla.' :
      config.processingMode === 'huggingface' ? 'Supabase conectada · Procesamiento en Hugging Face, sin worker de Render.' + (config.driveConnected ? ' Drive autorizado.' : ' Puedes conectar Drive después.') : config.driveConnected ? 'Supabase conectada · Drive autorizado. La subida automática necesita el worker activo.' : 'Supabase conectada · Autoriza Google Drive para subir videos automáticamente con el worker activo.';
    if (config.processingMode === 'huggingface' && !config.transcriptionProviderConfigured) status.textContent += ' Falta configurar HF_TOKEN y el endpoint en Render.';
    const callback = new URLSearchParams(location.search).get('drive');
    if (callback === 'error') status.textContent = 'No se pudo completar la autorización de Drive. Revisa la configuración OAuth y vuelve a conectar.';
    if (callback === 'cancelled') status.textContent = 'La autorización de Drive fue cancelada.';
  }).catch(error => { status.textContent = error.message; });
  load();
})();
