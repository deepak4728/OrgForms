/* Stable field IDs and explicit reference targets; server remains authoritative. */
(() => {
  const form = document.querySelector('#dataset-definition-form');
  if (!form) return;
  const json = form.querySelector('[name=schema]'), list = document.querySelector('#dataset-field-list');
  const error = document.querySelector('#dataset-schema-error'), raw = document.querySelector('#dataset-use-json');
  const lookups = JSON.parse(document.querySelector('#dataset-lookup-choices').textContent);
  const types = ['text','textarea','email','tel','number','select','radio','date','checkbox','rating',...(form.dataset.uiElement?['file','multiselect','time','heading','paragraph','image','item_cards']:['record_reference'])];
  let base = {};
  document.querySelector('#component-draft')?.addEventListener('click', async event => {
    const button=event.currentTarget,status=document.querySelector('#component-draft-status');button.disabled=true;status.textContent='Drafting component…';
    try {const response=await fetch(button.dataset.url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify({prompt:document.querySelector('#component-prompt').value})});const result=await response.json();if(!response.ok)throw Error(result.error||'Draft failed.');form.elements.name.value=result.name;form.elements.description.value=result.description;json.value=JSON.stringify(result.schema);load();raw.checked=false;status.textContent='Review the fields, then save your component.';}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  });
  function control(parent, caption, tag = 'input') {
    const label = document.createElement('label'); label.textContent = caption;
    const input = document.createElement(tag); label.append(input); parent.append(label); return input;
  }
  function add(field = {}) {
    const row = document.createElement('div'); row.className = 'schema-field';
    const main = document.createElement('div'); main.className = 'schema-field-main'; row.append(main);
    const label = control(main, 'Label'); label.value = field.label || '';
    const id = control(main, 'Field ID'); id.value = field.id || ''; id.required = true; id.pattern = '[A-Za-z][A-Za-z0-9_\x2d]{0,79}';
    label.addEventListener('input', () => { if (!id.dataset.edited) id.value = ('field_' + label.value.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'')).slice(0,80); });
    id.addEventListener('input', () => { id.dataset.edited = '1'; }); if (field.id) id.dataset.edited = '1';
    const type = control(main, 'Type', 'select');
    types.forEach(kind => { const option = document.createElement('option'); option.value = kind; option.textContent = ({text:'Short answer',textarea:'Paragraph answer',radio:'Multiple choice',multiselect:'Checkboxes',checkbox:'Yes / no',paragraph:'Text / instructions',image:'Display image (not upload)',heading:'Display heading (not input)',paragraph:'Display text (not input)',item_cards:'Library item cards'}[kind] || kind.replaceAll('_',' ')); type.append(option); });
    type.value = field.type || 'text';
    const required = control(main, 'Required'); required.type = 'checkbox'; required.checked = !!field.required;
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary'; remove.textContent = '×'; remove.title = 'Remove field'; remove.setAttribute('aria-label', 'Remove field'); remove.onclick = () => row.remove(); main.append(remove);
    const order = document.createElement('div'); order.className = 'schema-field-order';
    [['Move up', -1], ['Move down', 1]].forEach(([caption, direction]) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary';
      button.textContent = direction < 0 ? '↑' : '↓'; button.setAttribute('aria-label', caption);
      button.onclick = () => { const sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling; if (sibling) { if(direction < 0) list.insertBefore(row, sibling); else list.insertBefore(sibling, row); } };
      order.append(button);
    });
    row.append(order);
    const extras = document.createElement('div'); extras.className = 'schema-field-options'; row.append(extras);
    const options = control(extras, 'Choices (comma separated)'); options.value = (field.options || []).join(', ');
    const min = control(extras, 'Minimum'); min.type = 'number'; min.step = 'any'; min.value = field.min ?? '';
    const max = control(extras, 'Maximum'); max.type = 'number'; max.step = 'any'; max.value = field.max ?? '';
    const lookup = control(extras, 'Lookup dataset', 'select');
    lookup.append(new Option('Choose a dataset', '')); lookups.forEach(item => lookup.append(new Option(item.name, item.id))); lookup.value = field.dataset_id || '';
    const content = control(extras, 'Display text / instructions', 'textarea'); content.value = field.content || '';
    const src = control(extras, 'Image URL (HTTPS)'); src.value = field.src || '';
    const placeholder = control(extras, 'Input placeholder'); placeholder.value = field.placeholder || '';
    function refresh() { const display=['heading','paragraph','image'].includes(type.value); required.parentElement.hidden=display; if(display)required.checked=false; content.parentElement.hidden=!['heading','paragraph'].includes(type.value); src.parentElement.hidden=type.value!=='image'; placeholder.parentElement.hidden=!['text','textarea','email','tel'].includes(type.value); options.parentElement.hidden = !['select','radio','multiselect'].includes(type.value); min.parentElement.hidden = max.parentElement.hidden = !['number','rating'].includes(type.value); lookup.parentElement.hidden = type.value !== 'record_reference'; }
    type.addEventListener('change', refresh); refresh();
    row.definition = () => {
      const value = {...field, id:id.value.trim(), label:label.value.trim(), type:type.value, required:required.checked};
      delete value.options; delete value.min; delete value.max; delete value.dataset_id;
      if (['select','radio','multiselect'].includes(type.value)) value.options = options.value.split(',').map(s=>s.trim()).filter(Boolean);
      if (['number','rating'].includes(type.value)) { if(min.value !== '') value.min = Number(min.value); if(max.value !== '') value.max = Number(max.value); }
      if (type.value === 'record_reference') value.dataset_id = lookup.value;
      delete value.content; delete value.src; delete value.placeholder;
      if(['heading','paragraph'].includes(type.value))value.content=content.value;
      if(type.value==='image')value.src=src.value;
      if(['text','textarea','email','tel'].includes(type.value))value.placeholder=placeholder.value;
      return value;
    };
    list.append(row);
  }
  document.querySelector('#component-preview-button')?.addEventListener('click', () => {
    const preview=document.querySelector('#component-preview');preview.replaceChildren();const legend=document.createElement('legend');legend.textContent=form.elements.name.value||'Component preview';preview.append(legend);preview.hidden=false;
    for(const row of list.children){const field=row.definition(),label=document.createElement('label');label.textContent=field.label;label.style.display='block';
      if(['heading','paragraph'].includes(field.type)){const text=document.createElement(field.type==='heading'?'h3':'p');text.textContent=field.content||field.label;preview.append(text);continue;}
      if(field.type==='image'){const image=document.createElement('img');if(field.src?.startsWith('https://'))image.src=field.src;image.alt=field.label;image.style.maxWidth='100%';preview.append(image);continue;}
      if(field.type==='item_cards'){const sample=document.createElement('p');sample.textContent='Current Library items appear here in the form, with images, descriptions, availability and quantity controls.';preview.append(sample);continue;}
      const input=document.createElement(['textarea'].includes(field.type)?'textarea':['select','radio','multiselect'].includes(field.type)?'select':'input');
      if(input.tagName==='SELECT'){for(const option of field.options||[])input.append(new Option(option,option));input.multiple=field.type==='multiselect';}else input.type=({number:'number',rating:'number',email:'email',tel:'tel',date:'date',time:'time',checkbox:'checkbox',file:'file'}[field.type]||'text');
      input.placeholder=field.placeholder||'';if(field.min!==undefined)input.min=field.min;if(field.max!==undefined)input.max=field.max;label.append(input);preview.append(label);
    }
  });
  function load() { const schema = JSON.parse(json.value); if (!Array.isArray(schema.fields)) throw Error('The schema needs a fields list.'); base = schema; list.replaceChildren(); schema.fields.forEach(add); error.hidden = true; }
  function fail(message) { error.textContent = message; error.hidden = false; }
  try { load(); } catch { raw.checked = true; fail('Review the JSON definition before saving.'); }
  document.querySelector('#dataset-add-field').onclick = () => add();
  document.querySelector('#dataset-load-json').onclick = () => { try { load(); raw.checked = false; } catch(e) { fail(e.message); } };
  form.addEventListener('submit', event => {
    try {
      if (raw.checked) JSON.parse(json.value);
      else { const fields = [...list.children].map(row=>row.definition()); if (!fields.length || fields.some(f=>!f.id||!f.label)) throw Error('Every dataset needs fields with stable IDs and labels.'); if(new Set(fields.map(f=>f.id)).size !== fields.length) throw Error('Each field ID must be unique.'); json.value = JSON.stringify({...base, fields}); }
    } catch(e) { event.preventDefault(); fail(e.message); }
  });
  raw.addEventListener('change', () => { list.querySelectorAll('input,select,textarea').forEach(input => input.disabled = raw.checked); });
})();
