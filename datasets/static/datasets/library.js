(() => {
  const dialog = document.getElementById('library-dataset-dialog');
  const frame = document.getElementById('library-dataset-frame');
  if (!dialog || !frame) return;
  document.querySelector('[data-open-dialog="library-dataset-dialog"]')?.addEventListener('click', () => {
    frame.src = frame.dataset.src;
  });
  dialog.addEventListener('close', () => { frame.src = 'about:blank'; });
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
    if (event.data?.type === 'orgforms:library-saved') location.assign(location.pathname + '?view=datasets');
    else if (event.data?.type === 'orgforms:library-close' || event.data?.type === 'orgforms:close') dialog.close();
  });
})();
