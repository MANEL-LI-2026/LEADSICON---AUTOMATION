window.LibraryApi = {
  async request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}, body: JSON.stringify(body)
    });
    if (response.status === 401) { location.assign('/login'); throw new Error('Inicia sesión para continuar.'); }
    let data; try { data = await response.json(); } catch { throw new Error('No se pudo completar la solicitud.'); }
    if (!response.ok) throw new Error(data.error || 'No se pudo completar la solicitud.');
    return data;
  }
};
