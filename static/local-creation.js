(() => {
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const describeError = data => data.detail || Object.values(data).flat().join(' ') || 'The request failed.';
  async function post(url, body) {
    const response = await fetch(url, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(describeError(data));
    return data;
  }
  for (const controls of document.querySelectorAll('[data-local-creation]')) {
    const models = controls.querySelector('[data-creation-model]');
    const status = controls.querySelector('[data-creation-status]') || controls.parentElement.querySelector('[data-creation-status]');
    const loadModels = () => fetch('/api/creation/models/' + (controls.dataset.organization ? `?org=${encodeURIComponent(controls.dataset.organization)}` : ''))
      .then(async response => { const data=await response.json(); if (!response.ok) throw new Error(describeError(data)); return data; })
      .then(data => {
        const previous=models.value;
        models.replaceChildren();
        if (data.models.length && !data.default && !models.hidden) { const option=new Option('Default model unavailable — choose a model',''); option.disabled=true; models.append(option); }
        for (const name of data.models) { const option=document.createElement('option'); option.value=name; option.textContent=name === data.default && !models.hidden ? `${name} · Default` : name; models.append(option); }
        if (data.models.includes(previous)) models.value=previous;
        else if (data.default) models.value=data.default;
        else if (!models.hidden) models.value='';
        if (!data.models.length) { const option=document.createElement('option'); option.value=''; option.textContent=data.ollama_running?'No installed models':'Start Ollama in AI Hub'; models.append(option); }
        if (status) status.textContent = !data.ollama_running ? 'Start Ollama in AI Hub to generate drafts.' : !data.default ? (models.hidden ? 'Choose an installed default model in AI Hub before drafting.' : 'The default model is unavailable. Choose an installed model.') : '';
      }).catch(error => { models.replaceChildren(new Option('Models unavailable','')); if(status)status.textContent=error.message; });
    controls.querySelector('[data-creation-refresh]')?.addEventListener('click',loadModels);
    loadModels();
  }
  const generate = document.getElementById('organization-generate');
  if (!generate) return;
  const prompt = document.getElementById('organization-draft-prompt');
  const status = document.getElementById('organization-draft-status');
  const initial = document.getElementById('organization-initial-form');
  const preview = document.getElementById('organization-form-preview');
  const summary = document.getElementById('organization-form-summary');
  function renderInitial(draft) {
    summary.replaceChildren(); preview.hidden=!draft;
    if (!draft) return;
    const title=document.createElement('h4');title.textContent=draft.title;
    const list=document.createElement('ol');
    for (const field of draft.fields) { const row=document.createElement('li');row.textContent=`${field.label} · ${field.type}${field.required?' · required':''}`;list.append(row); }
    summary.append(title,list);
  }
  if (initial.value) { document.getElementById('organization-include-form').checked=true; try {renderInitial(JSON.parse(initial.value));} catch {status.textContent='Discard the invalid first form and generate a new draft.';preview.hidden=false;} }
  document.getElementById('organization-include-form').addEventListener('change',event=>{if(!event.target.checked){initial.value='';renderInitial(null);}});
  document.getElementById('organization-discard-form').addEventListener('click',()=>{initial.value='';renderInitial(null);});
  generate.addEventListener('click',async () => {
    if (!prompt.value.trim()) {status.textContent='Describe your organization first.';prompt.focus();return;}
    const requestPrompt=prompt.value, includeForm=document.getElementById('organization-include-form').checked;
    const form=document.getElementById('organization-create-form');
    const currentDetails=()=>JSON.stringify([...form.querySelectorAll('#org-name,#org-description,#org-purpose,#org-type,[data-profile-address],[data-profile-key]')].map(input=>[input.id,input.value]));
    const before=currentDetails();
    generate.disabled=true;status.textContent='Drafting locally; thinking models may take longer…';
    try {
      const data=await post('/api/creation/organization/',{prompt:requestPrompt,model:document.querySelector('[data-creation-model]').value,include_form:includeForm});
      if(prompt.value!==requestPrompt || document.getElementById('organization-include-form').checked!==includeForm || currentDetails()!==before) throw new Error('The prompt or details changed while drafting. Please try again.');
      for (const key of ['name','description','purpose']) document.getElementById(`org-${key}`).value=data.organization[key]||'';
      document.querySelector(`#create-workspace-dialog [data-org-type-choice="${data.organization.business_type}"]`)?.click();
      for (const key of ['address','phone','email']) {
        const value=data.organization[key];
        const input=key==='address' ? form.querySelector('[data-profile-address]') : form.querySelector(`[data-profile-key="${key}"]`);
        if (value && input) { input.value=value; input.dispatchEvent(new Event('input',{bubbles:true})); }
      }
      if (data.organization.phone || data.organization.email) form.querySelector('.org-wizard-extra').open=true;
      initial.value=data.initial_form?JSON.stringify(data.initial_form):'';renderInitial(data.initial_form);
      status.textContent=`Draft ready · ${data.model} · ${data.thinking===true?(data.reasoning_mode==='planned'?'Thinking used for planning':data.reasoning_mode==='thinking_attempted'?'Thinking attempted; review carefully':'Thinking on'):data.thinking===false?'Thinking unavailable':'Thinking support unverified'}. Review the organization details below, then choose Create organization. ${(data.warnings||[]).join(' ')}`;
      const reviewStatus=document.getElementById('organization-review-status');
      reviewStatus.textContent=(data.warnings||[]).join(' '); reviewStatus.hidden=!reviewStatus.textContent;
      document.getElementById('organization-create-form').dispatchEvent(new CustomEvent('organization-draft-ready'));
      document.getElementById('org-name').focus();
    } catch(error) {status.textContent=error.message;}
    finally {generate.disabled=false;}
  });
})();
