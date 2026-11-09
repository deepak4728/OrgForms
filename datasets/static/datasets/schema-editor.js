/* Stable field IDs and explicit reference targets; server remains authoritative. */
(() => {
  const form = document.querySelector('#dataset-definition-form');
  if (!form) return;
  const json = form.querySelector('[name=schema]'), list = document.querySelector('#dataset-field-list');
  const error = document.querySelector('#dataset-schema-error'), raw = document.querySelector('#dataset-use-json');
  const lookups = JSON.parse(document.querySelector('#dataset-lookup-choices').textContent);
  const types = ['text','textarea','email','tel','number','select','radio','date','checkbox','rating',...(form.dataset.uiElement?['quantity','file','multiselect','time','heading','paragraph','image','item_cards']:['record_reference'])];
  let base = {};
  let activeRow=null;
  function clearActiveField(){if(activeRow)activeRow.classList.remove('is-active');activeRow=null;}

  const layoutControl=document.getElementById('section-layout');
  function updateCanvas(){
    if(!layoutControl)return;
    list.dataset.layout=layoutControl.value;
    document.getElementById('saved-section-canvas-title').textContent=form.elements.name.value||'New section';
  }
  layoutControl?.addEventListener('change',()=>{base.layout=layoutControl.value;for(const row of list.children){row.sectionLayout=layoutControl.value;}updateCanvas();});
  form.elements.name?.addEventListener('input',updateCanvas);
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
    row.dataset.width=field.layout_width||'auto';
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
    function refresh() { const display=['heading','paragraph','image'].includes(type.value); required.parentElement.hidden=display; if(display)required.checked=false; content.parentElement.hidden=!['heading','paragraph'].includes(type.value); src.parentElement.hidden=type.value!=='image'; placeholder.parentElement.hidden=!['text','textarea','email','tel'].includes(type.value); options.parentElement.hidden = !['select','radio','multiselect'].includes(type.value); min.parentElement.hidden = max.parentElement.hidden = !['number','rating','quantity'].includes(type.value); lookup.parentElement.hidden = type.value !== 'record_reference'; }
    type.addEventListener('change', refresh); refresh();
    row.definition = () => {
      const value = {...field, id:id.value.trim(), label:label.value.trim(), type:type.value, required:required.checked};
      delete value.options; delete value.min; delete value.max; delete value.dataset_id;
      if (['select','radio','multiselect'].includes(type.value)) value.options = options.value.split(',').map(s=>s.trim()).filter(Boolean);
      if (['number','rating','quantity'].includes(type.value)) { if(min.value !== '') value.min = Number(min.value); if(max.value !== '') value.max = Number(max.value); }
      if (type.value === 'record_reference') value.dataset_id = lookup.value;
      delete value.content; delete value.src; delete value.placeholder;
      if(['heading','paragraph'].includes(type.value))value.content=content.value;
      if(type.value==='image')value.src=src.value;
      if(['text','textarea','email','tel'].includes(type.value))value.placeholder=placeholder.value;
      if(row.sectionLayout&&value.ui_group)value.ui_group_layout=row.sectionLayout;
      return value;
    };
    if(form.dataset.uiElement){
      const optional=document.createElement('details');optional.className='saved-section-field-advanced';const optionalTitle=document.createElement('summary');optionalTitle.textContent='Settings';row.insertBefore(optional,extras);optional.append(optionalTitle,extras);optional.open=false;type.addEventListener('change',()=>{optional.open=false;});
      const advanced=document.createElement('details');advanced.className='saved-section-field-advanced';const summary=document.createElement('summary');summary.textContent='Field ID';advanced.append(summary,id.parentElement);row.append(advanced);
      required.parentElement.classList.add('data-check');
      const tools=document.createElement('div');tools.className='section-field-tools';
      const toolbar=document.createElement('div');toolbar.className='section-field-toolbar';
      toolbar.append(required.parentElement,order,remove);tools.append(toolbar,optional,advanced);tools.setAttribute('role','region');tools.setAttribute('aria-label','Selected field tools');row.append(tools);
      for(const detail of [optional,advanced])detail.addEventListener('toggle',()=>{if(detail.open)for(const sibling of [optional,advanced])if(sibling!==detail)sibling.open=false;});
      const activate=()=>{
        if(activeRow===row)return;
        clearActiveField();activeRow=row;row.classList.add('is-active');
      };
      const originalRemove=remove.onclick;remove.onclick=event=>{event.stopPropagation();if(activeRow===row)clearActiveField();originalRemove();};
      row.addEventListener('focusin',activate);row.addEventListener('click',activate);

      const captions={text:'Written answer',textarea:'Written answer · paragraph',email:'Email',tel:'Phone',number:'Number',quantity:'Quantity − / +',select:'Choose one · dropdown',radio:'Choose one',multiselect:'Choose several',checkbox:'Yes or no',heading:'Heading',paragraph:'Show text',image:'Show image',item_cards:'Show items',file:'File upload',rating:'Rating',date:'Date',time:'Time'};
      for(const option of type.options)option.textContent=captions[option.value]||option.textContent;
    }
    list.append(row);
    if(form.dataset.uiElement&&Object.keys(field).length===0)label.focus();
  }
  document.querySelector('#component-preview-button')?.addEventListener('click', () => {
    try {
      const schema = raw.checked ? JSON.parse(json.value) : {...base, fields:[...list.children].map(row => row.definition())};
      if (!Array.isArray(schema.fields)) throw Error('The section needs a fields list.');
      const preview = document.querySelector('#component-preview');
      const fields = structuredClone(schema.fields);
      const roots = new Set(fields.map(field=>field.ui_group_path?.[0]?.id || field.ui_group || 'root'));
      for (const field of fields) {
        if (field.type === 'item_cards' && !field.catalog_id) field.item_source = 'organization';
        if (!field.ui_group) Object.assign(field, {ui_group:'preview_section', ui_group_label:form.elements.name.value || 'Section', ui_group_layout:schema.layout || 'grid'});
      }
      if (roots.size === 1) for (const field of fields) {
        if (field.ui_group_path?.length) field.ui_group_path[0].label = form.elements.name.value;
        else field.ui_group_label = form.elements.name.value;
      }
      OrgFormsFields.mount({schema:{...schema, fields}, root:preview.querySelector('#fields'),
        menu:JSON.parse(document.querySelector('#section-preview-items').textContent) || [],
        fieldCatalogs:Object.fromEntries(fields.filter(field=>field.catalog_id).map(field=>[field.id,field.catalog_id]))});
      preview.hidden = false;
      preview.scrollIntoView({block:'start'});
    } catch (e) { fail(e.message); }
  });

  function load() { const schema = JSON.parse(json.value); if (!Array.isArray(schema.fields)) throw Error('The schema needs a fields list.'); base = schema; clearActiveField(); list.replaceChildren(); schema.fields.forEach(add); if(layoutControl){layoutControl.value=schema.layout||'grid';updateCanvas();} error.hidden = true; }
  list.closest('.saved-section-canvas')?.addEventListener('click',event=>{if(!event.target.closest('.schema-field'))clearActiveField();});
  function fail(message) { error.textContent = message; error.hidden = false; }
  try { load(); } catch { raw.checked = true; fail('Review the JSON definition before saving.'); }
  document.querySelector('#dataset-add-field').onclick = () => add();
  document.querySelector('#dataset-load-json').onclick = () => { try { load(); raw.checked = false; } catch(e) { fail(e.message); } };
  form.addEventListener('submit', event => {
    try {
      if (raw.checked) JSON.parse(json.value);
      else { const fields = [...list.children].map(row=>row.definition()); if (!fields.length || fields.some(f=>!f.id||!f.label)) throw Error(form.dataset.uiElement?'Give every field a label. Open Advanced field ID only if an ID needs fixing.':'Every dataset needs fields with stable IDs and labels.'); if(new Set(fields.map(f=>f.id)).size !== fields.length) throw Error('Each field ID must be unique.'); json.value = JSON.stringify({...base, fields}); }
    } catch(e) { event.preventDefault(); fail(e.message); }
  });
  raw.addEventListener('change', () => { list.querySelectorAll('input,select,textarea').forEach(input => input.disabled = raw.checked); });
})();
