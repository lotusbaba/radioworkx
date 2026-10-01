(() => {
  const opener = document.getElementById('open-catalog-search');
  if (!opener) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'music-dialog catalog-search-dialog';
  dialog.setAttribute('aria-labelledby', 'catalog-search-title');
  dialog.innerHTML = `<button type="button" class="catalog-search-close" aria-label="Close search">×</button>
    <h2 id="catalog-search-title">Search the collection</h2>
    <form id="catalog-search-form"><label for="catalog-search-kind">Search by</label>
    <select id="catalog-search-kind"><option value="artist">Artist</option><option value="album">Album</option><option value="track">Track</option></select>
    <label for="catalog-search-query">Search text</label>
    <input id="catalog-search-query" type="search" maxlength="200" autocomplete="off" placeholder="Enter an artist name">
    <button type="submit">Search</button></form>
    <p id="catalog-search-status" role="status" aria-live="polite">Enter a name to search.</p>
    <div id="catalog-search-results"></div>`;
  document.body.append(dialog);
  const query = dialog.querySelector('input');
  const kind = dialog.querySelector('select');
  const status = dialog.querySelector('#catalog-search-status');
  const results = dialog.querySelector('#catalog-search-results');
  let timer, controller, version = 0;
  function invalidate() {
    clearTimeout(timer);
    controller?.abort();
    version++;
    results.replaceChildren();
  }
  async function search() {
    invalidate();
    const text = query.value.trim();
    if (!text) { status.textContent = 'Enter a name to search.'; return; }
    const current = version;
    controller = new AbortController();
    status.textContent = 'Searching…';
    try {
      const response = await fetch('/api/library/search?' + new URLSearchParams({kind: kind.value, q: text}), {signal: controller.signal});
      if (!response.ok) throw new Error('Search is unavailable. Please try again.');
      const data = await response.json();
      if (current !== version || !dialog.open) return;
      status.textContent = data.total ? `${data.total} ${data.total === 1 ? "result" : "results"}${data.total > data.items.length ? ' · Showing the first 25; refine your search for more.' : ''}` : 'No matches. Try another name or search type.';
      for (const item of data.items) {
        const card = document.createElement('a');
        card.className = 'catalog-search-result';
        card.href = item.url;
        const title = document.createElement('strong');
        title.textContent = item.name;
        const detail = document.createElement('span');
        detail.textContent = item.kind === 'artist' ? 'Artist · Open artist page' : item.artists.join(', ') + (item.kind === 'track' ? ' · Open album' : ' · Album');
        card.append(title, detail);
        results.append(card);
      }
    } catch (error) {
      if (current === version && error.name !== 'AbortError') status.textContent = 'Search is unavailable. Please try again.';
    }
  }
  opener.addEventListener('click', () => { dialog.showModal(); query.focus(); });
  dialog.querySelector('.catalog-search-close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => {
    invalidate(); query.value = ''; status.textContent = 'Enter a name to search.'; opener.focus();
  });
  dialog.querySelector('form').onsubmit = event => { event.preventDefault(); search(); };
  query.oninput = () => {
    invalidate();
    status.textContent = query.value.trim() ? 'Searching…' : 'Enter a name to search.';
    if (query.value.trim()) timer = setTimeout(search, 250);
  };
  kind.onchange = () => {
    query.placeholder = `Enter ${kind.value === 'artist' || kind.value === 'album' ? 'an' : 'a'} ${kind.value} name`;
    search();
  };
})();
