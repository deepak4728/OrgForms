(() => {
  document.querySelectorAll('[data-library-draft]').forEach(panel => {
    const form = panel.closest('form');
    const button = panel.querySelector('[data-draft-button]');
    const status = panel.querySelector('[data-draft-status]');
    button.addEventListener('click', async () => {
      const prompt = panel.querySelector('textarea').value.trim();
      if (!prompt) { status.textContent = 'Describe what you want to create first.'; return; }
      button.disabled = true;
      status.textContent = 'Preparing a local draft…';
      try {
        const response = await fetch(panel.dataset.url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify({prompt})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Unable to create a draft.');
        const draft = result.draft;
        form.elements.name.value = draft.name;
        form.elements.description.value = draft.description;
        if (panel.dataset.kind === 'item') {
          form.elements.category.value = draft.category;
          form.elements.price.value = '';
          status.textContent = 'Review the item and enter its price before adding it.';
        } else {
          form.elements.schema.value = JSON.stringify(draft.schema, null, 2);
          document.querySelector('#dataset-load-json').click();
          status.textContent = 'Review the dataset name and fields before saving.';
        }
      } catch (error) { status.textContent = error.message; }
      finally { button.disabled = false; }
    });
  });
})();
