const form = document.querySelector('#search');
const statusText = document.querySelector('#status');
const results = document.querySelector('#results');
const button = document.querySelector('#submit');
const download = document.querySelector('#download');
let exportItems = [];
const keywordPresets = {
  organic: ['#fyp', '#viral', '#blessing', '#car', '#Challenge'],
  paid: ['Cheap Insurance', 'Auto Insurance', 'Low Car Insurance Rates', 'Lower your rate'],
};
let keywordMode = 'paid';
const keywordDrafts = Object.fromEntries(Object.entries(keywordPresets).map(([mode, words]) => [mode, words.join('\n')]));
const keywordInput = document.querySelector('#keywords');
function keywords() {
  return [...new Set(keywordInput.value.split('\n').map(value => value.trim()).filter(Boolean))];
}
function updateKeywords() {
  keywordDrafts[keywordMode] = keywordInput.value;
  document.querySelector('#keyword-count').textContent = `${keywords().length} palabras clave`;
  document.querySelector('#keyword-feedback').textContent = '';
}
keywordInput.addEventListener('input', updateKeywords);
document.querySelectorAll('[data-keyword-mode]').forEach(tab => tab.addEventListener('click', () => {
  keywordDrafts[keywordMode] = keywordInput.value;
  keywordMode = tab.dataset.keywordMode;
  keywordInput.value = keywordDrafts[keywordMode];
  document.querySelectorAll('[data-keyword-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.keywordMode === keywordMode)));
  updateKeywords();
}));
document.querySelector('#reset-keywords').addEventListener('click', () => {
  keywordInput.value = keywordPresets[keywordMode].join('\n');
  updateKeywords();
});
document.querySelector('#apply-keywords').addEventListener('click', () => {
  const feedback = document.querySelector('#keyword-feedback');
  const field = document.querySelector('#keyword-field').value.trim();
  if (!field || ['__proto__', 'constructor', 'prototype'].includes(field) || field.includes('.')) {
    feedback.textContent = 'Indica un campo de primer nivel válido según la documentación del Actor.'; return;
  }
  const words = keywords();
  if (!words.length) { feedback.textContent = 'Añade al menos una palabra clave.'; return; }
  const actorInput = document.querySelector('#actor-input');
  let input;
  try {
    input = JSON.parse(actorInput.value.trim() || '{}');
    if (!input || Array.isArray(input) || typeof input !== 'object') throw new Error();
  } catch { feedback.textContent = 'Corrige el JSON antes de aplicar las keywords.'; return; }
  input[field] = document.querySelector('#keyword-format').value === 'array' ? words : words.join('\n');
  actorInput.value = JSON.stringify(input, null, 2);
  feedback.textContent = `Aplicadas ${words.length} palabras clave a «${field}». Si las editas después, vuelve a aplicarlas al JSON.`;
});
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}});
  if (response.status === 401) { location.assign('/login'); throw new Error('La sesión expiró.'); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Error ${response.status}`);
  return body;
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  let input;
  try {
    input = JSON.parse(document.querySelector('#actor-input').value);
    if (!input || Array.isArray(input) || typeof input !== 'object') throw new Error();
  } catch { statusText.textContent = 'Introduce un objeto JSON válido.'; return; }
  button.disabled = true;
  download.hidden = true;
  results.textContent = '';
  statusText.textContent = 'Iniciando búsqueda…';
  try {
    const run = await api('/api/runs', {method: 'POST', body: JSON.stringify({platform: document.querySelector('#platform').value, input})});
    const deadline = Date.now() + 600000;
    while (true) {
      const current = await api(`/api/runs/${encodeURIComponent(run.id)}`);
      statusText.textContent = `Búsqueda ${current.id}: ${current.status}`;
      if (current.status === 'SUCCEEDED') {
        exportItems = current.items;
        results.textContent = JSON.stringify(exportItems, null, 2);
        download.hidden = false;
        break;
      }
      if (!['READY', 'RUNNING', 'TIMING-OUT', 'ABORTING'].includes(current.status)) throw new Error(`La búsqueda terminó: ${current.status}.`);
      if (Date.now() >= deadline) throw new Error(`Se agotó la espera. El run ${run.id} puede seguir activo; revísalo en Apify antes de repetir.`);
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  } catch (error) { statusText.textContent = `${error.message} Si la búsqueda ya se inició, revisa Apify antes de repetir.`; }
  finally { button.disabled = false; }
});
download.addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(exportItems, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url; link.download = 'anuncios.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
