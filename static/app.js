const $ = id => document.getElementById(id);
const presets = {
  organic: ['#fyp', '#viral', '#blessing', '#car', '#Challenge'],
  paid: ['Cheap Insurance', 'Auto Insurance', 'Low Car Insurance Rates', 'Lower your rate'],
};
const storageKey = 'leadsicon-ads-search-v2', pageSize = 12;
const drafts = Object.fromEntries(Object.entries(presets).map(([key, words]) => [key, words.join('\n')]));
let mode = 'paid', busy = false, page = 0, exportItems = [], navigating = false;
let state = {version: 2, phase: 'idle', fields: {}, completed: [], activeRun: null, next: 0, items: [], saved: {}, warnings: []};
function persist() {
  state.fields = Object.fromEntries(['platform','keywords','search-by','advertisers','search-region','result-limit'].map(id => [id, $(id).value]));
  state.mode = mode; state.drafts = drafts; state.page = page;
  try { sessionStorage.setItem(storageKey, JSON.stringify(state)); }
  catch {
    // Keep run IDs even if provider records exceed browser storage; refetch previews on return.
    try { sessionStorage.setItem(storageKey, JSON.stringify({...state, items: [], saved: {}, refetch: true})); }
    catch { $('status').textContent = 'El navegador no permite conservar esta búsqueda. Los runs iniciados siguen en Apify.'; }
  }
}
function showResults(visible) {
  $('search-panel').hidden = visible; $('results-panel').hidden = !visible;
  document.querySelector('.ads-workspace').classList.toggle('has-results', visible);
}
function update() {
  drafts[mode] = $('keywords').value;
  const count = new Set($('keywords').value.split('\n').map(word => word.trim()).filter(Boolean)).size;
  $('keyword-count').textContent = `${count} palabras clave`;
  $('organic-notice').hidden = mode !== 'organic';
  for (const id of ['submit', 'preview-input']) $(id).disabled = busy || mode === 'organic';
  $('advertiser-fields').hidden = $('search-by').value !== 'advertiser';
  $('keywords').disabled = busy || $('search-by').value === 'advertiser';
  const facebook = $('platform').value === 'facebook';
  $('advertisers').placeholder = facebook ? 'https://www.facebook.com/tu-pagina' : 'dominio.com\nAR… (ID de anunciante)';
  $('advertiser-help').textContent = facebook ? 'Para Meta, pega URLs de páginas de Facebook o de su biblioteca de anuncios.' : 'Para YouTube, introduce nombres de anunciantes, dominios o IDs de Google. El Actor detecta el tipo.';
  $('input-preview').hidden = true; $('view-results').hidden = !state.plan;
  document.querySelectorAll('[data-keyword-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.keywordMode === mode)));
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}});
  if (response.status === 401) { location.assign('/login'); throw Error('La sesión expiró.'); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(body.error || `Error ${response.status}`);
  return body;
}
function plan() {
  return api('/api/scraper/plan', {method: 'POST', body: JSON.stringify({platform: $('platform').value, mode, searchBy: $('search-by').value,
    queries: $('search-by').value === 'advertiser' ? $('advertisers').value : $('keywords').value,
    region: $('search-region').value, limit: Number($('result-limit').value)})});
}
function status(message) { state.message = message; $('status').textContent = message; persist(); }
function render() {
  exportItems = state.items || [];
  const pages = Math.max(1, Math.ceil(exportItems.length / pageSize)); page = Math.min(page, pages - 1);
  const offset = page * pageSize;
  AdResults.render($('results'), exportItems.slice(offset, offset + pageSize), state.plan?.platform || $('platform').value, {
    entries: exportItems.slice(offset, offset + pageSize).map((_, index) => state.saved[offset + index]),
    onSaved: (index, saved) => { state.saved[offset + index] = {id:saved.id, liked:saved.liked, platform:saved.platform, kind:saved.kind}; persist(); }
  });
  $('results').hidden = !exportItems.length && busy;
  $('results-pagination').hidden = exportItems.length <= pageSize;
  $('page-label').textContent = `Página ${page + 1} de ${pages} · ${exportItems.length} anuncios`;
  $('previous-page').disabled = page === 0; $('next-page').disabled = page + 1 === pages;
  $('download').hidden = !exportItems.length;
  $('search-summary').textContent = state.plan ? `${state.plan.platform === 'facebook' ? 'Facebook / Meta' : 'YouTube'} · ${state.plan.runs.map(run => run.label).join(' · ')}` : '';
  $('scraper-progress').hidden = !busy;
  $('results-panel').setAttribute('aria-busy', String(busy));
  $('resume-search').hidden = busy || !state.activeRun;
}
function setBusy(value) {
  busy = value;
  $('search').querySelectorAll('input, textarea, select, button').forEach(control => { control.disabled = value; });
  update(); render();
}
async function follow(runId, label) {
  const deadline = Date.now() + 600000;
  while (!navigating) {
    const current = await api(`/api/runs/${encodeURIComponent(runId)}`);
    const message = `${state.next + 1}/${state.plan.runs.length} · ${label} · ${current.status === 'RUNNING' ? 'Explorando anuncios…' : current.status}`;
    status(message); $('progress-caption').textContent = message;
    if (current.status === 'SUCCEEDED') return current.items || [];
    if (!['READY','RUNNING','TIMING-OUT','ABORTING'].includes(current.status)) throw Error(`El run terminó: ${current.status}.`);
    if (Date.now() >= deadline) throw Error('El run sigue sin finalizar. Puedes reanudar su seguimiento sin iniciar otra búsqueda.');
    await new Promise(resolve => setTimeout(resolve, 3000));
  }
  return null;
}
async function execute() {
  if (busy) return;
  showResults(true); setBusy(true);
  try {
    while (state.next < state.plan.runs.length && !navigating) {
      const query = state.plan.runs[state.next];
      if (!state.activeRun) {
        // Persist ambiguity before POST: never automatically repeat a possibly-paid start.
        state.phase = 'starting'; status(`Iniciando ${state.next + 1}/${state.plan.runs.length}: ${query.label}…`);
        const run = await api('/api/runs', {method:'POST', body:JSON.stringify({platform:state.plan.platform, input:query.input})});
        state.activeRun = run.id; state.phase = 'running';
        if (run.libraryWarning && !state.warnings.includes(run.libraryWarning)) state.warnings.push(run.libraryWarning);
        persist();
      }
      const items = await follow(state.activeRun, query.label);
      if (items === null) return;
      state.items.push(...items); state.completed.push(state.activeRun); state.activeRun = null; state.next++;
      state.phase = state.next < state.plan.runs.length ? 'between-runs' : 'completed'; persist(); render();
    }
    if (!navigating) { state.phase = 'completed'; status(`Búsqueda completada · ${state.items.length} anuncios. ${state.warnings.join(' ')}`); }
  } catch(error) {
    if (!navigating) {
      state.phase = state.activeRun ? 'paused' : 'uncertain';
      status(`${error.message} ${state.activeRun ? 'Reanuda el seguimiento para consultar el mismo run.' : 'No se confirmó el inicio. Revisa Apify antes de repetir.'}`);
    }
  } finally { if (!navigating) { setBusy(false); persist(); } }
}
$('search').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || mode !== 'paid') return;
  $('submit').disabled = true;
  try {
    const prepared = await plan();
    state = {version:2, phase:'between-runs', fields:{}, plan:prepared, next:0, activeRun:null, completed:[], items:[], saved:{}, warnings:[]}; page = 0;
    persist(); await execute();
  } catch(error) { $('status').textContent = error.message; showResults(true); }
  finally { update(); }
});
$('edit-search').addEventListener('click', () => { showResults(false); });
$('view-results').addEventListener('click', () => showResults(true));
$('resume-search').addEventListener('click', execute);
for (const [id, delta] of [['previous-page',-1],['next-page',1]]) $(id).addEventListener('click', () => { page += delta; render(); persist(); $('results-panel').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); });
for (const id of ['platform','keywords','search-by','advertisers','search-region','result-limit']) $(id).addEventListener('input', () => { update(); persist(); });
document.querySelectorAll('[data-keyword-mode]').forEach(tab => tab.addEventListener('click', () => {
  if (busy) return; drafts[mode] = $('keywords').value; mode = tab.dataset.keywordMode; $('keywords').value = drafts[mode]; update(); persist();
}));
$('reset-keywords').addEventListener('click', () => { $('keywords').value = presets[mode].join('\n'); update(); persist(); });
$('preview-input').addEventListener('click', async () => {
  try { const prepared = await plan(); $('input-preview').textContent = JSON.stringify(prepared,null,2); $('input-preview').hidden = false; }
  catch(error) { $('input-preview').textContent = error.message; $('input-preview').hidden = false; }
});
$('download').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(exportItems,null,2)],{type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'anuncios.json'; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
});
window.addEventListener('pagehide', () => { navigating = true; if (!window.leadsiconLoggingOut) persist(); });
window.addEventListener('pageshow', event => { if(event.persisted) location.reload(); });
(async function restore() {
  try {
    const cached = JSON.parse(sessionStorage.getItem(storageKey));
    if (cached?.version === 2 && Array.isArray(cached.items) && Array.isArray(cached.completed)) {
      state = cached; state.saved ||= {}; state.warnings ||= []; mode = state.mode === 'organic' ? 'organic' : 'paid'; page = Number(state.page) || 0;
      Object.assign(drafts,state.drafts || {});
      for (const [id,value] of Object.entries(state.fields || {})) if ($(id) && typeof value === 'string') $(id).value = value;
      update(); if(state.plan) showResults(true);
      $('status').textContent = state.message || 'Búsqueda recuperada.';
      if (state.refetch) {
        setBusy(true); state.items = [];
        for (const id of state.completed) { const result = await api('/api/runs/' + encodeURIComponent(id)); state.items.push(...(result.items || [])); }
        state.refetch = false; setBusy(false); persist();
      }
      render();
      if(state.activeRun || state.phase === 'between-runs') await execute();
      else if(state.phase === 'starting') status('Saliste mientras se iniciaba un run. No repetiremos la petición: comprueba su estado en Apify antes de buscar otra vez.');
    } else update();
  } catch(error) { setBusy(false); showResults(true); status('No se pudo recuperar el seguimiento: ' + error.message); }
})();
