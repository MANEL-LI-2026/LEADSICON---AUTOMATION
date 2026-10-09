// Search references remain within the current authenticated browser tab.
document.querySelectorAll('form[action="/logout"]').forEach(form => form.addEventListener('submit', () => {
  window.leadsiconLoggingOut = true;
  try { sessionStorage.removeItem('leadsicon-ads-search-v2'); } catch {}
}));
