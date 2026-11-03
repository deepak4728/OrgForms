(() => {
  const dialog = document.getElementById('library-editor-dialog');
  const frame = document.getElementById('library-editor-frame');
  if (!dialog || !frame) return;
  let opener;
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-library-editor]');
    if (!link || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    opener = link;
    const url = new URL(link.href);
    url.searchParams.set('dialog', '1');
    document.getElementById('library-editor-title').textContent = link.dataset.libraryEditor;
    frame.title = link.dataset.libraryEditor;
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
