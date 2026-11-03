(() => {
  document.querySelectorAll('[data-item-options-editor]').forEach(editor => {
    const form = editor.closest('form'), output = form.elements.options;
    function sync() {
      output.value = JSON.stringify([...editor.children].map(row => ({label:row.querySelector('input').value.trim(), choices:row.querySelector('textarea').value.split(',').map(v=>v.trim()).filter(Boolean), required:row.querySelector('[type=checkbox]').checked,price_adjustments:Object.fromEntries(row.querySelector('[data-choice-prices]').value.split('\n').map(line=>line.split('=')).filter(parts=>parts.length===2&&parts[0].trim()&&parts[1].trim()).map(([choice,price])=>[choice.trim(),price.trim()]))})));
    }
    function add(option={}) {
      const row=document.createElement('div');row.className='surface surface-subtle';
      const label=document.createElement('input');label.placeholder='Field label, e.g. Spice level';label.setAttribute('aria-label','Option label');label.value=option.label||'';label.maxLength=100;
      const choices=document.createElement('textarea');choices.rows=2;choices.placeholder='Choices separated by commas: Mild, Medium, Hot';choices.setAttribute('aria-label','Available choices');choices.value=(option.choices||[]).join(', ');
      const prices=document.createElement('textarea');prices.dataset.choicePrices='';prices.rows=2;prices.placeholder='Optional price additions, one per line: Large = 40';prices.setAttribute('aria-label','Additional price per choice');prices.value=Object.entries(option.price_adjustments||{}).map(([choice,price])=>`${choice} = ${price}`).join('\n');
      const required=document.createElement('input');required.type='checkbox';required.checked=!!option.required;required.style.width='auto';const requiredLabel=document.createElement('label');requiredLabel.append(required,document.createTextNode(' Required'));
      const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='Remove';remove.onclick=()=>{row.remove();sync()};
      row.append(label,choices,prices,requiredLabel,remove);row.addEventListener('input',sync);editor.append(row);
    }
    form.querySelector('[data-add-item-option]').onclick=()=>{if(editor.children.length<12){add();sync()}};
    output.addEventListener('change',()=>{editor.replaceChildren();try{JSON.parse(output.value).forEach(add)}catch{}});
    form.addEventListener('submit',sync);
  });
})();
