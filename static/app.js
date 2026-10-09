const form = document.querySelector('#search');
const statusText = document.querySelector('#status');
const results = document.querySelector('#results');
const button = document.querySelector('#submit');
const download = document.querySelector('#download');
let exportItems = [];
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
