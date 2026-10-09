/* Interactive planning prototype: no transcription, AI or video generation. */
const fields = ['project-name', 'reference-url', 'idea', 'angle', 'audience', 'goal', 'treatment', 'keep', 'avoid', 'cta', 'hook', 'script', 'visual', 'style', 'duration', 'people', 'locations', 'formats'];
const $ = id => document.getElementById(id);
let step = 0;
let source = 'write';
const labels = ['Definir concepto →', 'Editar guion →', 'Elegir variantes →', 'Crear hoja de ruta →'];
const draftKey = 'leadsicon-ugc-draft-v1';
function lines(id) { return [...new Set($(id).value.split('\n').map(v => v.trim()).filter(Boolean))]; }
function combinations() {
  const count = lines('people').length * lines('locations').length * lines('formats').length;
  return count;
}
function feedback(text) { $('feedback').textContent = text; }
function updateSummary() {
  $('summary-title').textContent = $('project-name').value.trim() || 'Una nueva idea';
  $('summary-source').textContent = source === 'write' ? 'Idea escrita' : 'Video / anuncio de referencia';
  $('summary-goal').textContent = $('goal').value;
  $('summary-style').textContent = $('style').value;
  const count = combinations();
  $('summary-variants').textContent = count ? `${count} versiones` : 'Por definir';
  $('variant-count').textContent = count;
  $('change-fields').hidden = $('treatment').value === 'exact';
  const exact = $('treatment').value === 'exact';
  if (exact) {
    $('hook').value = '';
    $('script').value = $('idea').value;
  }
  $('hook').readOnly = exact;
  $('script').readOnly = exact;
}
function chooseSource(value) {
  source = value;
  document.querySelectorAll('[data-source]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.source === source)));
  $('reference-fields').hidden = source !== 'reference';
  $('idea-label').textContent = source === 'reference' ? 'Transcripción / descripción contextual' : '¿Qué tienes en mente?';
  updateSummary();
}
function validate(index) {
  let message = '';
  let focus;
  if (index === 0 && (!$('project-name').value.trim() || !$('idea').value.trim())) { message = 'Añade un nombre y escribe la idea o el contenido de referencia.'; focus = !$('project-name').value.trim() ? 'project-name' : 'idea'; }
  if (index === 0 && source === 'reference' && $('reference-url').value && !$('reference-url').checkValidity()) { message = 'Revisa el enlace de referencia.'; focus = 'reference-url'; }
  if (index === 1 && (!$('angle').value.trim() || !$('audience').value.trim() || !$('cta').value.trim())) { message = 'Define el ángulo, la audiencia y la llamada a la acción.'; focus = !$('angle').value.trim() ? 'angle' : !$('audience').value.trim() ? 'audience' : 'cta'; }
  if (index === 2 && !$('script').value.trim()) { message = 'Escribe el desarrollo del guion antes de elegir variantes.'; focus = 'script'; }
  if (index === 3 && !combinations()) { message = 'Añade al menos una persona, una locación y un formato.'; focus = !lines('people').length ? 'people' : !lines('locations').length ? 'locations' : 'formats'; }
  if (index === 3 && combinations() > 100) { message = 'Este mockup admite hasta 100 variantes. Reduce las opciones.'; focus = 'people'; }
  if (message) { feedback(message); $(focus).focus(); return false; }
  return true;
}
function showStep(next) {
  if (next > step) {
    for (let index = 0; index < next; index++) {
      if (!validate(index)) {
        if (index !== step) { showStep(index); validate(index); }
        return;
      }
    }
  }
  if (next === 2 && $('treatment').value === 'exact') {
    $('hook').value = '';
    $('script').value = $('idea').value;
  }
  step = next;
  document.querySelectorAll('[data-panel]').forEach(panel => panel.hidden = Number(panel.dataset.panel) !== step);
  document.querySelectorAll('[data-step]').forEach(button => {
    button.classList.toggle('active', Number(button.dataset.step) === step);
    button.classList.toggle('done', Number(button.dataset.step) < step);
    if (Number(button.dataset.step) === step) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  });
  $('back').disabled = step === 0;
  $('next').hidden = step === 4;
  $('next').textContent = labels[step] || '';
  $('step-caption').textContent = `Paso ${step + 1} de 5`;
  feedback('');
  if (step === 4) renderRoadmap();
}
function project() {
  return {schemaVersion: 1, source, step, fields: Object.fromEntries(fields.map(id => [id, $(id).value]))};
}
function variants() {
  if (combinations() > 100) return [];
  const list = [];
  for (const person of lines('people')) for (const location of lines('locations')) for (const format of lines('formats')) {
    list.push({id: `V${String(list.length + 1).padStart(2, '0')}`, person, location, format, status: 'Por producir'});
  }
  return list;
}
function renderRoadmap() {
  const brief = $('roadmap-brief');
  brief.replaceChildren();
  const heading = document.createElement('h3');
  heading.textContent = $('project-name').value;
  brief.append(heading);
  for (const [label, value] of [['Ángulo', $('angle').value], ['Audiencia', $('audience').value], ['Hook', $('hook').value], ['Guion', $('script').value], ['CTA', $('cta').value], ['Dirección visual', $('visual').value], ['Conservar', $('keep').value], ['Cambiar', $('avoid').value]]) {
    if (!value || ($('treatment').value === 'exact' && ['Conservar', 'Cambiar'].includes(label))) continue;
    const paragraph = document.createElement('p');
    const title = document.createElement('strong'); title.textContent = `${label}: `;
    paragraph.append(title, document.createTextNode(value)); brief.append(paragraph);
  }
  const rows = $('roadmap-rows'); rows.replaceChildren();
  for (const variant of variants()) {
    const row = document.createElement('tr');
    for (const value of [variant.id, variant.person, variant.location, variant.format, variant.status]) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }
    rows.append(row);
  }
}
fields.forEach(id => $(id).addEventListener('input', updateSummary));
document.querySelectorAll('[data-source]').forEach(button => button.addEventListener('click', () => chooseSource(button.dataset.source)));
document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => showStep(Number(button.dataset.step))));
$('next').addEventListener('click', () => showStep(Math.min(4, step + 1)));
$('back').addEventListener('click', () => showStep(Math.max(0, step - 1)));
$('save-draft').addEventListener('click', () => {
  try { sessionStorage.setItem(draftKey, JSON.stringify(project())); feedback('Borrador guardado en esta pestaña.'); }
  catch { feedback('El navegador no permitió guardar el borrador.'); }
});
$('load-draft').addEventListener('click', () => {
  try {
    const draft = JSON.parse(sessionStorage.getItem(draftKey));
    if (!draft || draft.schemaVersion !== 1 || !draft.fields) { feedback('Todavía no hay un borrador guardado en esta pestaña.'); return; }
    if (!confirm('¿Recuperar el borrador? Se reemplazará el contenido actual.')) return;
    fields.forEach(id => { if (typeof draft.fields[id] === 'string') $(id).value = draft.fields[id]; });
    chooseSource(draft.source === 'reference' ? 'reference' : 'write');
    step = 0; showStep(0); feedback('Borrador recuperado.');
  } catch { feedback('No se pudo recuperar el borrador.'); }
});
$('new-project').addEventListener('click', () => {
  if (!confirm('¿Empezar un proyecto nuevo? Los cambios sin guardar se perderán.')) return;
  fields.forEach(id => { const field = $(id); if (field.tagName === 'SELECT') field.selectedIndex = 0; else field.value = ''; });
  chooseSource('write'); step = 0; showStep(0);
});
$('example').addEventListener('click', () => {
  if (fields.some(id => $(id).tagName !== 'SELECT' && $(id).value.trim()) && !confirm('¿Reemplazar el contenido con el ejemplo?')) return;
  const example = {'project-name': 'De perseguir clientes a tener conversaciones', idea: 'Una dueña de negocio cuenta que pasaba más tiempo buscando clientes que atendiendo su negocio. Descubre una forma de organizar su captación con Leadsicon.', angle: 'Pasar de improvisar la captación a tener un proceso claro.', audience: 'Dueños de negocios de servicios', keep: 'Historia en primera persona y tono cercano.', avoid: 'Promesas de resultados garantizados o cifras sin comprobar.', cta: 'Conoce cómo puede ayudarte Leadsicon.', hook: '¿También terminas el día pensando de dónde va a salir tu próximo cliente?', script: 'Yo estaba pendiente de publicar, responder mensajes y buscar oportunidades, todo al mismo tiempo. Quería ordenar mi captación y dedicarle más atención a mi negocio. Por eso empecé a explorar Leadsicon: para entender qué podía mejorar en mi proceso y dar el siguiente paso con más claridad.', visual: 'Video vertical grabado con iPhone. Persona hablando a cámara en su lugar de trabajo. Insertos de su agenda y tareas del día.', people: 'Dueña de negocio, 35 años\nEmprendedor, 28 años', locations: 'Oficina\nEn casa', formats: 'Testimonio selfie\nVoz en off con escenas'};
  fields.forEach(id => { if ($(id).tagName === 'SELECT') $(id).selectedIndex = 0; else $(id).value = example[id] || ''; });
  chooseSource('write'); updateSummary(); feedback('Ejemplo cargado. Puedes editarlo y recorrer los cinco pasos.');
});
$('export').addEventListener('click', () => {
  for (let index = 0; index < 4; index++) if (!validate(index)) return;
  const result = {...project(), prototype: true, variants: variants(), generatedAt: new Date().toISOString()};
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'leadsicon-ugc-brief.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000); feedback('Brief y hoja de ruta exportados.');
});
chooseSource('write'); showStep(0);
