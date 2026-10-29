(() => {
  const dialog = document.getElementById('create-workspace-dialog');
  const form = document.getElementById('organization-create-form');
  if (!dialog || !form) return;
  const steps = [...form.querySelectorAll('[data-wizard-step]')];
  const indicators = [...dialog.querySelectorAll('[data-wizard-indicator]')];
  const next = form.querySelector('.org-wizard-actions [data-wizard-next]');
  const back = form.querySelector('[data-wizard-back]');
  const submit = form.querySelector('[data-wizard-submit]');
  let current = Number(dialog.dataset.startStep) || 0;
  function show(step) {
    current = Math.max(0, Math.min(steps.length - 1, step));
    steps.forEach((panel, index) => { panel.hidden = index !== current; });
    indicators.forEach((indicator, index) => { if (index === current) indicator.setAttribute('aria-current', 'step'); else indicator.removeAttribute('aria-current'); });
    back.hidden = current === 0;
    next.hidden = current === 0 || current === steps.length - 1;
    submit.hidden = current !== steps.length - 1;
    if (current === steps.length - 1) {
      form.querySelector('[data-review-name]').textContent = form.elements.name.value.trim();
      const type = form.elements.business_type;
      form.querySelector('[data-review-type]').textContent = form.querySelector('[data-custom-category]')?.value.trim() || type.selectedOptions[0]?.textContent || '';
      const emails = form.elements.member_emails.value.trim().split(/[,;\s]+/).filter(Boolean);
      form.querySelector('[data-review-members]').textContent = emails.length ? `You + ${emails.length} account${emails.length === 1 ? '' : 's'}` : 'Just you';
    }
    dialog.scrollTop = 0;
  }
  function advance() {
    for (const input of steps[current].querySelectorAll('input, select, textarea')) {
      if (input.willValidate && !input.checkValidity()) { input.reportValidity(); return; }
    }
    show(current + 1);
  }
  form.querySelectorAll('[data-wizard-next]').forEach(button => button.addEventListener('click', advance));
  back.addEventListener('click', () => show(current - 1));
  form.addEventListener('organization-draft-ready', () => show(1));
  form.addEventListener('submit', event => { if (current !== steps.length - 1) { event.preventDefault(); advance(); } });
  show(current);
})();
