const conversation = document.querySelector('#conversation');
const input = document.querySelector('#chat-message');
const model = document.querySelector('#chat-model');
const send = document.querySelector('#send-chat');
const feedback = document.querySelector('#chat-feedback');
const reset = document.querySelector('#new-chat');
let messages = [];
let busy = false;
function render() {
  conversation.querySelectorAll('.chat-message').forEach(element => element.remove());
  document.querySelector('#chat-empty').hidden = messages.length > 0;
  for (const message of messages) {
    const bubble = document.createElement('div'); bubble.className = `chat-message ${message.role}`;
    const name = document.createElement('strong'); name.textContent = message.role === 'user' ? 'Tú' : 'Asistente';
    const text = document.createElement('p'); text.textContent = message.content;
    bubble.append(name, text); conversation.append(bubble);
  }
  conversation.scrollTop = conversation.scrollHeight;
}
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
  if (input.disabled) return;
  input.value = button.dataset.prompt; input.focus();
}));
reset.addEventListener('click', () => {
  if (busy || (messages.length && !confirm('¿Borrar la conversación actual?'))) return;
  messages = []; input.value = ''; feedback.textContent = ''; render();
});
document.querySelector('#chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  const content = input.value.trim();
  if (busy || !content || input.disabled) return;
  // Keep complete user/assistant pairs, within the server's bounded history.
  let history = [...messages, {role: 'user', content}];
  while (history.length > 19 || history.reduce((size, item) => size + item.content.length, 0) > 24000 || history.slice(0, -1).some(item => item.content.length > 6000)) history.splice(0, 2);
  busy = true; send.disabled = true; model.disabled = true; reset.disabled = true; input.disabled = true;
  feedback.textContent = 'Esperando la respuesta…';
  try {
    const response = await fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}, body: JSON.stringify({model: model.value, messages: history})});
    if (response.status === 401) { location.assign('/login'); return; }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(body.error || `Error ${response.status}`);
    messages = [...history, {role: 'assistant', content: body.content}];
    input.value = ''; render(); feedback.textContent = '';
  } catch (error) { feedback.textContent = `${error.message} No se reintentará automáticamente.`; }
  finally { busy = false; send.disabled = false; model.disabled = false; reset.disabled = false; input.disabled = false; }
});
