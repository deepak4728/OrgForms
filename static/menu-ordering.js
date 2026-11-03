/* A Library-backed menu keeps display data separate from respondent selections. */
window.OrgFormsMenu = {
  mount(root, items, field) {
    const lines = [];
    const money = value => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(value / 100);
    const cents = value => Math.round(Number(value || 0) * 100);
    const node = (tag, cls, text) => { const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el; };
    const button = (text, action, cls='secondary') => { const el=node('button',cls,text);el.type='button';el.onclick=action;return el; };
    const unit = line => cents(line.item.price) + (line.item.options||[]).reduce((sum,option)=>sum+cents(option.price_adjustments?.[line.options[option.label]]),0);
    const limit = item => Math.min(50,item.stock ?? 50);
    const selected = item => lines.filter(line=>line.item.id===item.id).reduce((sum,line)=>sum+line.quantity,0);
    let category='', query='', grid=false, opener=null;
    root.classList.add('ordering-menu');
    const tools=node('div','ordering-menu-tools');
    const search=node('input');search.type='search';search.placeholder='Search items';search.setAttribute('aria-label','Search menu items');
    const view=button('Grid view',()=>{grid=!grid;view.textContent=grid?'List view':'Grid view';view.setAttribute('aria-pressed',String(grid));renderItems();});view.setAttribute('aria-pressed','false');
    tools.append(search,view);
    const categories=node('nav','ordering-categories');categories.setAttribute('aria-label','Item categories');
    const content=node('div','ordering-items');
    const summary=node('div','ordering-cart-bar');summary.hidden=true;
    const summaryText=node('span');summaryText.setAttribute('aria-live','polite');
    const review=button('Review cart',()=>openReview(),'ordering-review-button');summary.append(summaryText,review);
    const dialog=node('dialog','ordering-dialog');dialog.setAttribute('aria-label','Item options and selection review');
    root.append(tools,categories,content,summary,dialog);
    dialog.addEventListener('close',()=>opener?.focus());
    dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}});
    const show = title => {
      opener=document.activeElement;dialog.replaceChildren();
      const header=node('header','ordering-dialog-header');header.append(node('h3','',title),button('×',()=>dialog.close(),'ordering-close'));
      header.lastChild.setAttribute('aria-label','Close');dialog.append(header);
      if(!dialog.open)dialog.showModal();header.lastChild.focus();
      return dialog;
    };
    const notify = () => { root.dispatchEvent(new Event('change',{bubbles:true}));renderItems();updateSummary(); };
    function updateSummary() {
      const count=lines.reduce((sum,line)=>sum+line.quantity,0),total=lines.reduce((sum,line)=>sum+unit(line)*line.quantity,0);
      summary.hidden=!count;summaryText.textContent=`${count} item${count===1?'':'s'} · ${money(total)}`;
    }
    function openItem(item, editing=null) {
      const body=show(item.name);if(item.description)body.append(node('p','muted',item.description));
      const form=node('form','ordering-options');
      const choices={...(editing?.options||{})};
      for(const option of item.options||[]) {
        const group=node('fieldset','ordering-choice-group');group.append(node('legend','',option.label+(option.required?' *':'')));
        const select=node('select');select.setAttribute('aria-label',option.label);select.required=!!option.required;
        select.append(new Option('Choose '+option.label,''));
        for(const choice of option.choices) {const extra=cents(option.price_adjustments?.[choice]);select.append(new Option(choice+(extra?' · +'+money(extra):''),choice));}
        select.value=choices[option.label]||'';select.onchange=()=>{choices[option.label]=select.value;updateTotal();};group.append(select);form.append(group);
      }
      const quantityLabel=node('label','ordering-quantity-label','Quantity');
      const stepper=node('div','ordering-stepper');const quantity=node('input');quantity.type='number';quantity.min='1';quantity.step='1';quantity.value=String(editing?.quantity||1);quantity.required=true;quantity.setAttribute('aria-label','Item quantity');
      const available=limit(item)-selected(item)+(editing?.quantity||0);quantity.max=String(Math.max(1,available));
      stepper.append(button('−',()=>{quantity.value=String(Math.max(1,Number(quantity.value)-1));updateTotal();}),quantity,button('+',()=>{quantity.value=String(Math.min(Number(quantity.max),Number(quantity.value)+1));updateTotal();}));
      stepper.firstChild.setAttribute('aria-label','Decrease quantity');stepper.lastChild.setAttribute('aria-label','Increase quantity');quantity.oninput=updateTotal;
      quantityLabel.append(stepper);form.append(quantityLabel);
      const notesLabel=node('label','','Special instructions (optional)'),notes=node('textarea');notes.maxLength=500;notes.rows=2;notes.placeholder='For this item only';notes.value=editing?.notes||'';notesLabel.append(notes);form.append(notesLabel);
      const footer=node('footer','ordering-dialog-footer'),total=node('strong'),add=node('button','',editing?'Save item':'Add to cart');add.type='submit';add.disabled=available<1;footer.append(total,add);form.append(footer);body.append(form);
      function updateTotal(){total.textContent=money(unit({item,options:choices})*(Number(quantity.value)||0));}
      updateTotal();
      form.onsubmit=event=>{
        event.preventDefault();event.stopPropagation();if(!form.reportValidity())return;
        const count=Number(quantity.value);if(!Number.isInteger(count)||count<1||count>available)return;
        const options=Object.fromEntries(Object.entries(choices).filter(([,value])=>value));
        const entry={item,options,notes:notes.value.trim(),quantity:count};
        if(editing)lines.splice(lines.indexOf(editing),1);
        const match=lines.find(line=>line.item.id===item.id&&JSON.stringify(line.options)===JSON.stringify(options)&&line.notes===entry.notes);
        if(match)match.quantity+=count;else lines.push(entry);
        dialog.close();notify();
      };
    }
    function openReview() {
      const body=show('Review your cart'),list=node('div','ordering-review-lines');
      if(!lines.length)list.append(node('p','muted','Your cart is empty.'));
      for(const line of lines) {
        const row=node('article','ordering-review-line'),details=node('div');details.append(node('strong','',line.item.name));
        const options=Object.entries(line.options).map(([name,value])=>`${name}: ${value}`).join(' · ');if(options)details.append(node('p','muted',options));if(line.notes)details.append(node('p','muted',line.notes));
        details.append(node('small','',`${line.quantity} × ${money(unit(line))}`));
        const actions=node('div','ordering-line-actions');actions.append(node('strong','',money(unit(line)*line.quantity)),button('Edit',()=>openItem(line.item,line)),button('Remove',()=>{lines.splice(lines.indexOf(line),1);notify();openReview();}));
        row.append(details,actions);list.append(row);
      }
      body.append(list,node('p','ordering-subtotal','Items subtotal: '+money(lines.reduce((sum,line)=>sum+unit(line)*line.quantity,0))),node('p','muted','Final pricing and availability are checked when you submit. Applicable catalog tax and discounts are calculated by the server.'));
      body.append(button('Continue with form',()=>dialog.close()));
    }
    function renderCategories() {
      categories.replaceChildren();for(const name of ['',...new Set(items.map(item=>item.category||'General'))]) {
        const choice=button(name||'All',()=>{category=name;renderCategories();renderItems();});choice.setAttribute('aria-pressed',String(category===name));categories.append(choice);
      }
    }
    function renderItems() {
      content.replaceChildren();content.classList.toggle('is-grid',grid);
      const visible=items.filter(item=>(!category||(item.category||'General')===category)&&`${item.name} ${item.description||''}`.toLowerCase().includes(query));
      for(const item of visible) {
        const card=node('article','ordering-item'),details=node('div','ordering-item-details');details.append(node('h3','',item.name),node('strong','ordering-price',money(cents(item.price))));
        if(item.description)details.append(node('p','muted',item.description));
        if(item.stock!==null&&item.stock!==undefined)details.append(node('small','muted',item.stock===0?'Unavailable':`${item.stock} available`));
        const media=node('div','ordering-item-media');if(item.image_url?.startsWith('https://')){const image=node('img');image.src=item.image_url;image.alt=item.name;image.loading='lazy';image.referrerPolicy='no-referrer';image.onerror=()=>{image.hidden=true;};media.append(image);}
        const count=selected(item);const add=button(item.stock===0?'Unavailable':count?`${count} added · Add more`:'＋ Add',()=>openItem(item));add.disabled=count>=limit(item);add.setAttribute('aria-label','Add '+item.name);media.append(add);
        if(item.options?.length)media.append(node('small','muted','Customizable'));
        card.append(details,media);content.append(card);
      }
      if(!visible.length)content.append(node('p','muted',items.length?'No items match your search.':'No available Library items yet.'));
    }
    search.oninput=()=>{query=search.value.trim().toLowerCase();renderItems();};renderCategories();renderItems();
    return { values:()=>lines.map(line=>({menu_item_id:line.item.id,quantity:line.quantity,options:{...line.options},notes:line.notes})), reset:()=>{lines.splice(0);if(dialog.open)dialog.close();notify();} };
  }
};
