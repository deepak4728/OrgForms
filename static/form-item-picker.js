window.setupLibraryItemPicker=(card,field,type)=>{
 const picker=document.createElement('section');picker.dataset.itemPicker='';picker.className='builder-item-picker';card.append(picker);
 let source=field.item_source||(field.catalog_id?'catalog':'organization'),chosen=new Set(field.item_ids||[]),items=[];
 picker.dataset.source=source;
 const label=document.createElement('label');label.textContent='Which items should people see?';
 const mode=document.createElement('select');mode.setAttribute('aria-label','Items to show');for(const [value,text]of [['all','All Library items'],['category','A category'],['selected','Selected items']])mode.append(new Option(text,value));
 if(source==='catalog')mode.append(new Option('Existing catalog selection','legacy'));
 mode.value=field.item_ids?'selected':field.item_category?'category':source==='catalog'?'legacy':'all';
 const category=document.createElement('select');category.setAttribute('aria-label','Item category');
 const refresh=document.createElement('button');refresh.type='button';refresh.className='secondary';refresh.textContent='Refresh';
 const status=document.createElement('p');status.className='muted';status.role='status';const grid=document.createElement('div');grid.className='builder-item-grid';
 label.append(mode);picker.append(label,category,refresh,status,grid);
 function render(){picker.dataset.mode=mode.value==='selected'?'selected':'all';picker.dataset.source=mode.value==='legacy'?'catalog':'organization';picker.dataset.category=mode.value==='category'?category.value:'';if(field.catalog_id)picker.dataset.catalogId=field.catalog_id;category.hidden=mode.value!=='category';
 let available=items;if(mode.value==='legacy')available=items.filter(item=>item.catalog_id===field.catalog_id);if(mode.value==='category')available=items.filter(item=>item.category===category.value);
 grid.replaceChildren();for(const item of available){const row=document.createElement('label');row.className='builder-item-choice';if(mode.value==='selected'){const check=document.createElement('input');check.type='checkbox';check.dataset.libraryItem='';check.value=item.id;check.checked=chosen.has(item.id);check.onchange=()=>check.checked?chosen.add(item.id):chosen.delete(item.id);row.append(check);}const text=document.createElement('span');const name=document.createElement('strong');name.textContent=item.name;const detail=document.createElement('small');detail.textContent=`₹${item.price} · ${item.stock==null?'Available':item.stock+' in stock'}`;text.append(name,detail);row.append(text);grid.append(row);}
 status.textContent=available.length?`${available.length} items · People choose quantity and options.`:'No items here yet. Add items in Library, then refresh.';
 }
 async function load(){refresh.disabled=true;status.textContent='Loading items…';try{const response=await fetch(document.getElementById('field-list').dataset.itemsUrl,{cache:'no-store'});if(!response.ok)throw Error('Could not load items.');items=await response.json();category.replaceChildren();for(const name of [...new Set(items.map(item=>item.category))].sort())category.append(new Option(name,name));if(field.item_category)category.value=field.item_category;render();}catch(error){status.textContent=error.message;}finally{refresh.disabled=false;}}
 mode.onchange=render;category.onchange=render;refresh.onclick=load;let loaded=false;function update(){picker.hidden=type.value!=='item_cards';if(!picker.hidden&&!loaded){loaded=true;load();}}type.addEventListener('change',update);update();
};
