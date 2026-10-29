/* Collection questions map to stable dataset fields only by explicit selection. */
(() => {
  const destination = document.querySelector('#collection-destination');
  if (!destination) return;
  const choices = JSON.parse(document.querySelector('#collection-dataset-choices').textContent);
  const output = document.querySelector('#collection-field-mapping'), rows = document.querySelector('#collection-mapping-rows');
  const hint = document.querySelector('#collection-mapping-hint'), list = document.querySelector('#field-list');
  let mapping; try { mapping = JSON.parse(output.value); } catch { mapping = {}; }
  function sources() {
    if(document.querySelector('#use-advanced').checked) { try { return JSON.parse(document.querySelector('#advanced-schema').value).fields || []; } catch { return []; } }
    return [...list.querySelectorAll('[data-field]')].map(card => ({id:card.dataset.customId || card.dataset.autoId, label:card.querySelector('input').value, type:card.querySelector('select').value, dataset_id:card.querySelector('[data-lookup]')?.value}));
  }
  function render() {
    const target = choices.find(item => item.id === destination.value); rows.replaceChildren();
    if(!target) { hint.textContent='Responses remain in this collection. Select a dataset to create reusable records.'; return; }
    hint.textContent='Each accepted response creates a record. Existing records are updated only with an explicit record ID and version.';
    const available = sources();
    for(const field of target.fields) {
      const wrap = document.createElement('div'); wrap.className='field';
      const label=document.createElement('label');label.textContent=`${field.label}${field.required?' *':''} · ${field.type.replaceAll('_',' ')}`;
      const select=document.createElement('select');select.setAttribute('aria-label',`Source for ${field.label}`);select.dataset.target=field.id;
      select.append(new Option('Not mapped',''));
      for(const source of available.filter(source=>source.id&&source.type===field.type&&(field.type!=='record_reference'||source.dataset_id===field.dataset_id))) select.append(new Option(`${source.label} (${source.id})`, source.id));
      select.value=Object.keys(mapping).find(key=>mapping[key]===field.id)||'';
      select.addEventListener('change', () => { for(const key of Object.keys(mapping)) if(mapping[key]===field.id)delete mapping[key]; if(select.value)mapping[select.value]=field.id; output.value=JSON.stringify(mapping); });
      label.append(select);wrap.append(label);rows.append(wrap);
    }
  }
  destination.addEventListener('change',()=>{mapping={};render();});
  list.addEventListener('input',render);list.addEventListener('change',render);
  new MutationObserver(render).observe(list,{childList:true});
  document.querySelector('#use-advanced').addEventListener('change',render);
  document.querySelector('#advanced-schema').addEventListener('input',render);
  document.querySelector('#form-editor').addEventListener('submit', () => {const valid={};if(destination.value)rows.querySelectorAll('select').forEach(select=>{if(select.value)valid[select.value]=select.dataset.target;});output.value=JSON.stringify(valid);}, true);
  render();
})();
