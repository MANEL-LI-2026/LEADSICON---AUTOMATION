/* Translate provider-specific records into a readable, safely rendered view. */
window.AdResults = (() => {
  const text = (...values) => values.find(value => typeof value === 'string' && value.trim()) || '';
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const list = value => Array.isArray(value) ? value : [];
  function safeUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return '';
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
    } catch { return ''; }
  }
  function date(value) {
    if (value === null || value === undefined || value === '') return '';
    const parsed = new Date(typeof value === 'number' ? value < 1e12 ? value * 1000 : value : value);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString().slice(0, 10);
  }
  function normalize(record, platform) {
    const raw = object(record);
    const snapshot = object(raw.snapshot);
    const creative = object(list(snapshot.cards)[0]);
    const image = object(list(snapshot.images)[0]);
    const video = object(list(snapshot.videos)[0]);
    const archiveId = raw.adArchiveId || raw.ad_archive_id;
    const adUrl = safeUrl(raw.adUrl) || safeUrl(raw.ad_url) || safeUrl(raw.adLibraryUrl) ||
      (archiveId ? `https://www.facebook.com/ads/library/?id=${encodeURIComponent(archiveId)}` : '');
    const imageUrl = [raw.imageUrl, image.originalImageUrl, image.original_image_url, image.resizedImageUrl,
      image.resized_image_url, creative.originalImageUrl, creative.original_image_url,
      creative.resizedImageUrl, creative.resized_image_url].map(safeUrl).find(Boolean) || '';
    const videoUrl = [raw.videoUrl, video.videoHdUrl, video.video_hd_url, video.videoSdUrl, video.video_sd_url,
      creative.videoHdUrl, creative.video_hd_url, creative.videoSdUrl, creative.video_sd_url].map(safeUrl).find(Boolean) || '';
    const poster = [video.videoPreviewImageUrl, video.video_preview_image_url, creative.videoPreviewImageUrl,
      creative.video_preview_image_url, imageUrl].map(safeUrl).find(Boolean) || '';
    const format = text(raw.adFormat, snapshot.displayFormat, snapshot.display_format) || (videoUrl ? 'video' : imageUrl ? 'image' : '');
    return {
      advertiser: text(raw.advertiserName, raw.pageName, raw.page_name, snapshot.pageName, snapshot.page_name) || 'Anunciante no indicado',
      title: text(creative.title, snapshot.title, raw.title),
      body: text(creative.body, object(snapshot.body).text, snapshot.body, raw.adText, raw.text),
      cta: text(creative.ctaText, creative.cta_text, snapshot.ctaText, snapshot.cta_text, snapshot.ctaType, snapshot.cta_type),
      destination: safeUrl(creative.linkUrl) || safeUrl(creative.link_url) || safeUrl(snapshot.linkUrl) || safeUrl(snapshot.link_url),
      adUrl, imageUrl, videoUrl, poster, previewUrl: safeUrl(raw.previewUrl), format,
      platform: platform === 'youtube' ? 'YouTube' : 'Facebook / Meta',
      firstShown: date(raw.firstShown || raw.startDate || raw.start_date),
      lastShown: date(raw.lastShown || raw.endDate || raw.end_date),
      active: typeof raw.isActive === 'boolean' ? raw.isActive : typeof raw.is_active === 'boolean' ? raw.is_active : null,
    };
  }
  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content) node.textContent = content;
    return node;
  }
  function link(url, label) {
    const node = element('a', 'outline', label);
    node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer';
    return node;
  }
  function render(container, records, platform) {
    container.replaceChildren();
    if (!records.length) {
      container.append(element('p', 'ad-empty', 'No se encontraron anuncios para esta búsqueda. Prueba otra keyword, anunciante o país.'));
      return;
    }
    for (const record of records) {
      const ad = normalize(record, platform);
      const card = element('article', 'ad-card');
      const media = element('div', 'ad-media');
      let asset;
      if (ad.videoUrl) {
        asset = element('video'); asset.controls = true; asset.preload = 'none'; asset.playsInline = true;
        asset.src = ad.videoUrl; if (ad.poster) asset.poster = ad.poster;
      } else if (ad.imageUrl) {
        asset = element('img'); asset.src = ad.imageUrl; asset.alt = `Creativo de ${ad.advertiser}`;
        asset.loading = 'lazy'; asset.referrerPolicy = 'no-referrer';
      }
      const fallback = () => media.replaceChildren(element('span', 'ad-media-placeholder', 'Vista previa no disponible. Abre el anuncio en su biblioteca.'));
      if (asset) { asset.addEventListener('error', fallback, {once: true}); media.append(asset); }
      else media.append(element('span', 'ad-media-placeholder', ad.previewUrl ? 'Este creativo se visualiza en la biblioteca externa.' : 'El proveedor no incluyó una vista previa.'));
      card.append(media);
      const content = element('div', 'ad-card-content');
      const tags = element('div', 'ad-tags');
      tags.append(element('span', 'tag', ad.platform));
      if (ad.format) tags.append(element('span', 'tag', ad.format));
      if (ad.active !== null) tags.append(element('span', 'tag', ad.active ? 'Activo' : 'Inactivo'));
      content.append(tags, element('h3', '', ad.advertiser));
      if (ad.title) content.append(element('strong', 'ad-title', ad.title));
      content.append(element('p', 'ad-copy', ad.body || 'El proveedor no incluyó el texto de este anuncio.'));
      if (ad.cta) content.append(element('p', 'hint', `Llamada a la acción: ${ad.cta}`));
      if (ad.firstShown || ad.lastShown) content.append(element('p', 'hint',
        [ad.firstShown ? `Primera aparición: ${ad.firstShown}` : '', ad.lastShown ? `Última aparición: ${ad.lastShown}` : ''].filter(Boolean).join(' · ')));
      const actions = element('div', 'ad-card-actions');
      if (ad.adUrl) actions.append(link(ad.adUrl, 'Ver anuncio →'));
      if (ad.previewUrl) actions.append(link(ad.previewUrl, 'Abrir creativo →'));
      if (ad.destination) actions.append(link(ad.destination, 'Página de destino →'));
      if (!actions.childElementCount) actions.append(element('p', 'hint', 'El proveedor no incluyó enlaces para este registro.'));
      content.append(actions); card.append(content); container.append(card);
    }
  }
  return {normalize, render, safeUrl};
})();
