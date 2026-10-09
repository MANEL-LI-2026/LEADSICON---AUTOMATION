const $ = id => document.getElementById(id);
const presets = {
  organic: ['#fyp', '#viral', '#blessing', '#car', '#Challenge'],
  paid: ['Cheap Insurance', 'Auto Insurance', 'Low Car Insurance Rates', 'Lower your rate'],
};
const drafts = Object.fromEntries(Object.entries(presets).map(([mode, words]) => [mode, words.join('\n')]));
let mode = 'paid';
let busy = false;
let exportItems = [];
function update() {
  drafts[mode] = $('keywords').value;
  const count = new Set($('keywords').value.split('\n').map(word => word.trim()).filter(Boolean)).size;
  $('keyword-count').textContent = `${count} palabras clave`;
  $('organic-notice').hidden = mode !== 'organic';
  $('submit').disabled = busy || mode === 'organic';
  $('preview-input').disabled = busy || mode === 'organic';
  $('advertiser-fields').hidden = $('search-by').value !== 'advertiser';
  $('keywords').disabled = $('search-by').value === 'advertiser';
  const facebook = $('platform').value === 'facebook';
  $('advertisers').placeholder = facebook ? 'https://www.facebook.com/tu-pagina' : 'dominio.com\nAR… (ID de anunciante)';
  $('advertiser-help').textContent = facebook ? 'Para Meta, pega URLs de páginas de Facebook o de su biblioteca de anuncios.' : 'Para YouTube, introduce nombres de anunciantes, dominios o IDs de Google. El Actor detecta el tipo.';
  $('input-preview').hidden = true;
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {
    'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content,
  }});
  if (response.status === 401) { location.assign('/login'); throw Error('La sesión expiró.'); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(body.error || `Error ${response.status}`);
  return body;
}
function plan() {
  return api('/api/scraper/plan', {method: 'POST', body: JSON.stringify({
    platform: $('platform').value, mode, searchBy: $('search-by').value,
    queries: $('search-by').value === 'advertiser' ? $('advertisers').value : $('keywords').value,
    region: $('search-region').value, limit: Number($('result-limit').value),
  })});
}
$('keywords').addEventListener('input', update);
for (const id of ['platform', 'search-by', 'search-region', 'result-limit', 'advertisers']) $(id).addEventListener('input', update);
document.querySelectorAll('[data-keyword-mode]').forEach(tab => tab.addEventListener('click', () => {
  if (busy) return;
  drafts[mode] = $('keywords').value;
  mode = tab.dataset.keywordMode;
  $('keywords').value = drafts[mode];
  document.querySelectorAll('[data-keyword-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.keywordMode === mode)));
  update();
}));
$('reset-keywords').addEventListener('click', () => { $('keywords').value = presets[mode].join('\n'); update(); });
$('preview-input').addEventListener('click', async () => {
  try {
    const prepared = await plan();
    $('input-preview').textContent = JSON.stringify(prepared, null, 2);
    $('input-preview').hidden = false;
    $('status').textContent = `${prepared.runs.length} run(s), hasta ${prepared.maximumResults} resultados. La vista previa no ejecuta Apify.`;
  } catch (error) { $('status').textContent = error.message; }
});
$('search').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || mode !== 'paid') return;
  busy = true;
  const controls = [...$('search').querySelectorAll('input, textarea, select, button')];
  const prior = controls.map(control => control.disabled);
  controls.forEach(control => control.disabled = true);
  exportItems = []; $('download').hidden = true; $('results').textContent = '';
  $('status').textContent = 'Preparando búsqueda…';
  let activeRun;
  try {
    const prepared = await plan();
    for (let index = 0; index < prepared.runs.length; index++) {
      const query = prepared.runs[index];
      $('status').textContent = `Iniciando ${index + 1}/${prepared.runs.length}: ${query.label}…`;
      activeRun = null;
      const run = await api('/api/runs', {method: 'POST', body: JSON.stringify({platform: prepared.platform, input: query.input})});
      activeRun = run.id;
      const deadline = Date.now() + 600000;
      while (true) {
        const current = await api(`/api/runs/${encodeURIComponent(run.id)}`);
        $('status').textContent = `${index + 1}/${prepared.runs.length} · ${query.label} · Run ${run.id}: ${current.status}`;
        if (current.status === 'SUCCEEDED') {
          exportItems.push(...current.items);
          $('results').textContent = JSON.stringify(exportItems, null, 2);
          $('download').hidden = false;
          break;
        }
        if (!['READY', 'RUNNING', 'TIMING-OUT', 'ABORTING'].includes(current.status)) throw Error(`El run terminó: ${current.status}.`);
        if (Date.now() >= deadline) throw Error('Se agotó la espera; el run puede seguir activo.');
        await new Promise(resolve => setTimeout(resolve, 3000));
      }
    }
    $('status').textContent = `Completado: ${exportItems.length} registros en la vista previa, ${prepared.runs.length} run(s).`;
  } catch (error) {
    $('status').textContent = `${error.message} ${activeRun ? `Run: ${activeRun}.` : ''} Revisa Apify antes de repetir. Los resultados ya obtenidos se conservan.`;
  } finally {
    busy = false;
    controls.forEach((control, index) => control.disabled = prior[index]);
    update();
  }
});
$('download').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(exportItems, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'anuncios.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
update();
