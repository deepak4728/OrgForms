(() => {
  document.addEventListener('input', event => {
    if (!event.target.matches('[data-library-search]')) return;
    const query = event.target.value.trim().toLocaleLowerCase();
    const scope = event.target.closest('[data-library-search-scope]') || document;
    let matches = 0;
    scope.querySelectorAll('[data-library-row]').forEach(row => {
      row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
      if (!row.hidden) matches++;
    });
    scope.querySelectorAll('[data-library-search-group]').forEach(group => {
      group.hidden = !group.querySelector('[data-library-row]:not([hidden])');
    });
    const empty = scope.querySelector('[data-library-search-empty]');
    if (empty) empty.hidden = matches > 0;
  });
  const dialog = document.getElementById('library-editor-dialog');
  const frame = document.getElementById('library-editor-frame');
  if (!dialog || !frame) return;
  let opener, sizeObserver;
  frame.addEventListener('load', () => {
    sizeObserver?.disconnect();
    try {
      const form = frame.contentDocument?.querySelector('.library-item-editor');
      dialog.classList.toggle('is-item-editor', Boolean(form));
      if (!form) { frame.style.height=''; dialog.style.height=''; return; }
      const fit = () => { const height=Math.ceil(form.getBoundingClientRect().height+28);frame.style.height=height+'px';dialog.style.height=(height+dialog.querySelector('.dialog-heading').getBoundingClientRect().height+2)+'px'; };
      sizeObserver = new ResizeObserver(fit); sizeObserver.observe(form); fit();
    } catch { /* Other destinations retain their normal frame layout. */ }
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-library-editor]');
    if (!link || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    opener = link;
    const url = new URL(link.href);
    url.searchParams.set('dialog', '1');
    document.getElementById('library-editor-title').textContent = link.dataset.libraryEditor;
    frame.title = link.dataset.libraryEditor;
    dialog.classList.toggle('is-item-editor', /\/library\/items\//.test(url.pathname));
    frame.src = url.href;
    dialog.showModal();
  });
  dialog.addEventListener('close', () => {
    frame.src = 'about:blank';
    if (opener?.isConnected) opener.focus();
  });
  window.addEventListener('message', async event => {
    if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
    if (['orgforms:library-close', 'orgforms:close'].includes(event.data?.type)) dialog.close();
    if (event.data?.type !== 'orgforms:library-saved') return;
    try {
      const response = await fetch(location.href, {cache: 'no-store'});
      if (!response.ok) throw new Error('Refresh failed');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const content = page.querySelector('.library-content');
      const header = page.querySelector('.library-header');
      if (!content || !header) throw new Error('Library unavailable');
      document.querySelector('.library-content').replaceWith(content);
      document.querySelector('.library-header').replaceWith(header);
      dialog.close();
      const heading = content.querySelector('h2');
      heading?.setAttribute('tabindex', '-1');
      heading?.focus();
    } catch {
      // Keep the same Library section if an in-place refresh is unavailable.
      location.reload();
    }
  });
})();
