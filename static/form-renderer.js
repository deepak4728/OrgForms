/* Shared respondent controls for live forms and section previews. */
window.OrgFormsFields = {mount({schema, root, menu = [], fieldCatalogs = {}, initialRecord = null, menuControllers = new Map()}) {
function updateConditions(){
  const byId=new Map(schema.fields.map(field=>[field.id,field]));
  function visible(field){
    if(!field.visibleWhen)return true;
    const parent=byId.get(field.visibleWhen.field);
    if(!parent||!visible(parent))return false;
    const input=root.querySelector(`[name="${CSS.escape(parent.id)}"]`);
    const value=parent.type==='radio'?root.querySelector(`[name="${CSS.escape(parent.id)}"]:checked`)?.value:parent.type==='multiselect'?[...root.querySelectorAll(`[name="${CSS.escape(parent.id)}"]:checked`)].map(item=>item.value):input?.type==='checkbox'?input.checked:input?.value;
    const expected=field.visibleWhen.equals;
    if(['number','rating','quantity'].includes(parent.type))return value!==''&&value!==undefined&&Number.isFinite(Number(value))&&Number(value)===Number(expected);
    return Array.isArray(value)&&Array.isArray(expected)?JSON.stringify(value)===JSON.stringify(expected):value===expected;
  }
  for(const field of schema.fields){
    const wrap=root.querySelector(`[data-field-id="${CSS.escape(field.id)}"]`);
    if(!wrap)continue;
    wrap.hidden=!visible(field);
    for(const input of wrap.querySelectorAll('input,select,textarea'))input.required=!wrap.hidden&&input.dataset.formRequired==='true';
  }
}

function renderFields(){
  root.innerHTML='';
  const groups=new Map();
  const groupContainer=(name,layout,showFrame)=>{const group=document.createElement(showFrame?'fieldset':'div');group.className='custom-ui-group'+(showFrame?'':' frameless-group');group.dataset.layout=layout||'grid';if(showFrame){const legend=document.createElement('legend');legend.textContent=name;group.append(legend);}return group;};
  for(const field of schema.fields){
    let parent=root;for(const ancestor of field.ui_group_path||[]){if(!groups.has(ancestor.id)){const group=groupContainer(ancestor.label,ancestor.layout,ancestor.show_frame!==false);parent.append(group);groups.set(ancestor.id,group);}parent=groups.get(ancestor.id);}let destination=parent;if(field.ui_group&&field.ui_group_label){if(!groups.has(field.ui_group)){const group=groupContainer(field.ui_group_label,field.ui_group_layout,field.ui_group_show_frame!==false);parent.append(group);groups.set(field.ui_group,group)}destination=groups.get(field.ui_group)}
    const wrap=document.createElement('div');wrap.className='field';wrap.dataset.fieldId=field.id;
    const wide=['textarea','file','item_cards'].includes(field.type); wrap.dataset.layoutWidth=wide?'full':(field.max_length&&field.max_length<=24?'third':'half');
    if(field.visibleWhen){wrap.dataset.whenField=field.visibleWhen.field;wrap.dataset.whenEquals=field.visibleWhen.equals}
    const label=document.createElement('label');label.htmlFor=`field-${field.id}`;label.id=`field-label-${field.id}`;label.textContent=field.label+(field.required?' *':'');wrap.append(label);
    if(['heading','paragraph','image'].includes(field.type)){
      wrap.replaceChildren();wrap.dataset.layoutWidth='full';
      const content=document.createElement(field.type==='heading'?'h3':field.type==='image'?'img':'p');
      if(field.type==='image'){if(field.src?.startsWith('https://'))content.src=field.src;content.alt=field.label;content.loading='lazy';content.referrerPolicy='no-referrer';content.style.maxWidth='100%';content.style.maxHeight='280px';content.style.objectFit='contain';}
      else content.textContent=field.content||field.label;
      wrap.append(content);destination.append(wrap);continue;
    }
    if(['radio','multiselect'].includes(field.type)){
      wrap.setAttribute('role','group');wrap.setAttribute('aria-labelledby',label.id);
      for(const value of field.options||[]){const choice=document.createElement('label');choice.className='choice-option';const input=document.createElement('input');input.type=field.type==='radio'?'radio':'checkbox';input.name=field.id;input.value=value;input.dataset.formRequired=String(field.type==='radio'&&!!field.required);const saved=initialRecord?.data[field.id];input.checked=Array.isArray(saved)?saved.includes(value):saved===value;input.addEventListener('change',updateConditions);choice.append(input,document.createTextNode(value));wrap.append(choice)}
      destination.append(wrap);continue;
    }
    if(field.type==='item_cards'){
      wrap.setAttribute('role','group');wrap.setAttribute('aria-labelledby',label.id);
      const fieldItems=menu.filter(item=>(field.item_source==='organization'||item.catalog_id===fieldCatalogs[field.id])&&(!field.item_category||item.category===field.item_category)&&(!field.item_ids||field.item_ids.includes(item.id)));
      menuControllers.set(field.id,OrgFormsMenu.mount(wrap,fieldItems,field));
      wrap.dataset.itemCards=field.id;destination.append(wrap);continue;
    }
    let input;
    if(field.type==='record_reference'){
      input=document.createElement('select');input.append(new Option('Choose a record',''));
      const selected=initialRecord?.data[field.id];if(selected)input.append(new Option(selected,selected));
      fetch(`/api/datasets/${encodeURIComponent(field.dataset_id)}/lookup/`).then(async response=>{if(!response.ok)throw Error('Lookup access is required to choose a record.');return response.json()}).then(result=>{for(const row of result.results){const old=Array.from(input.options).find(option=>option.value===row.id);if(old)old.textContent=row.label;else input.append(new Option(row.label,row.id))}if(selected)input.value=selected}).catch(error=>{const hint=document.createElement('small');hint.textContent=error.message;wrap.append(hint)});
    }else if(['select','radio'].includes(field.type)){
      input=document.createElement('select');
      if(field.required){const empty=document.createElement('option');empty.value='';empty.textContent='Choose an option';input.append(empty)}
      for(const optionValue of field.options||[]){const option=document.createElement('option');option.value=optionValue;option.textContent=optionValue;input.append(option)}
    }else if(field.type==='textarea')input=document.createElement('textarea');
    else if(field.type==='checkbox'){input=document.createElement('input');input.type='checkbox'}
    else{input=document.createElement('input');input.type=field.type==='tel'?'tel':['rating','quantity'].includes(field.type)?'number':field.type;if(field.type==='file')input.accept='.pdf,.docx,.jpg,.jpeg,.png,.webp';if(field.min!==undefined)input.min=field.min;if(field.max!==undefined)input.max=field.max}
    if(field.max_length&&['text','textarea','email','tel'].includes(field.type))input.maxLength=field.max_length;
    input.name=field.id;input.id=`field-${field.id}`;input.dataset.formRequired=String(!!field.required);if(field.placeholder)input.placeholder=field.placeholder;
    if(initialRecord&&Object.hasOwn(initialRecord.data,field.id)){if(input.type==='checkbox')input.checked=!!initialRecord.data[field.id];else input.value=initialRecord.data[field.id]}input.addEventListener('change',updateConditions);if(field.type==='quantity'){input.step='1';input.min=field.min??0;input.value=input.value||String(Math.max(0,Number(input.min)));const controls=document.createElement('div');controls.className='ordering-card-stepper quantity-field';for(const [caption,delta] of [['−',-1],['+',1]]){const control=document.createElement('button');control.type='button';control.textContent=caption;control.setAttribute('aria-label',(delta<0?'Decrease ':'Increase ')+field.label);control.onclick=()=>{const next=Math.max(Number(input.min),Math.min(field.max??Number.MAX_SAFE_INTEGER,(Number(input.value)||0)+delta));input.value=String(next);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));};if(delta<0)controls.append(control,input);else controls.append(control);}wrap.append(controls);}else wrap.append(input);if(field.type==='file'){const hint=document.createElement('small');hint.className='field-hint';hint.textContent='PDF, Word document, or image · up to 10 MB';wrap.append(hint)}destination.append(wrap);
  }
  updateConditions();
}
renderFields();
return {renderFields, updateConditions, menuControllers};
}};
