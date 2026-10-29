(() => {
  const root=document.querySelector('#ai-hub'), server=document.querySelector('#ai-ollama-server');
  if(!root || !server)return;
  const toggle=document.querySelector('#ai-ollama-toggle'),status=document.querySelector('#ai-ollama-status');
  const output=document.querySelector('#ai-ollama-ps-output'),running=document.querySelector('#ai-ollama-running');
  const org=document.querySelector('#ai-org-select'),dot=document.querySelector('#ai-ollama-dot');
  const defaults=document.querySelector('#ai-ollama-default'),save=document.querySelector('#ai-ollama-save-default'),feedback=document.querySelector('#ai-ollama-default-status');
  const csrf=document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  let current=null,changing=false,request=0;
  const endpoint=path=>`${path}?org=${encodeURIComponent(org.value)}`;
  async function read(path,options={}) {
    const response=await fetch(endpoint(path),{...options,signal:AbortSignal.timeout(20000)});
    const value=await response.json();if(!response.ok)throw Error(value.detail || 'The local command is unavailable.');return value;
  }
  function render(value) {
    current=value;toggle.setAttribute('aria-checked',String(value.running));toggle.textContent=value.running?'On':'Off';
    toggle.disabled=changing || !value.can_control || !value.installed || (value.running&&!value.managed);
    dot.classList.toggle('is-running',value.running);
    status.textContent=value.running?(value.managed?'Running · started by OrgForms':'Running externally · stop from its app/service'):(value.managed?'Starting… Refresh shortly.':value.installed?'Off · ready to start':'Ollama is missing from the server PATH.');
    if(!value.can_control)status.textContent+=' An admin or manager on this computer can control it.';
  }
  function renderProcesses(value) {
    output.textContent=value.output;running.replaceChildren();
    for(const model of value.models||[]) {
      const row=document.createElement('div');row.className='ai-runtime-model';
      const name=document.createElement('strong');name.textContent=model.name;
      const metrics=document.createElement('small');metrics.textContent=[model.size,model.processor,model.context?`${model.context} context`:''].filter(Boolean).join(' · ');
      row.append(name,metrics);running.append(row);
    }
    if(!running.children.length)running.textContent=value.running?'No models loaded.': 'Server off · no active models.';
  }
  async function refresh() {
    const id=++request,selectedOrg=org.value;
    const results=await Promise.allSettled([read('/api/ollama/server/'),read('/api/ollama/ps/'),read('/api/models/')]);
    if(id!==request||selectedOrg!==org.value)return;
    const [state,ps,models]=results;
    if(state.status==='fulfilled')render(state.value);else {current=null;toggle.disabled=true;status.textContent=state.reason.message;}
    if(ps.status==='fulfilled')renderProcesses(ps.value);else{running.textContent=ps.reason.message;output.textContent=ps.reason.message;}
    defaults.replaceChildren();feedback.textContent='';
    if(models.status==='fulfilled') {
      const available=(models.value.models||[]).filter(model=>model.available!==false);
      for(const model of available)defaults.add(new Option(model.name,model.name));
      defaults.value=models.value.default_model||'';
      if(!defaults.value&&available.length)defaults.selectedIndex=0;
      if(!available.length)defaults.add(new Option('No installed models available',''));
      defaults.disabled= !available.length;
      save.disabled=!current?.can_control||!available.length;
      if(models.value.default_model&&!available.some(model=>model.name===models.value.default_model))feedback.textContent='Configured default is unavailable. Choose an installed model.';
    } else {defaults.add(new Option('Start Ollama to load models',''));defaults.disabled=true;save.disabled=true;}
    fit();
  }
  toggle.addEventListener('click',async()=>{
    if(changing||!current||toggle.disabled)return;
    changing=true;toggle.disabled=true;status.textContent=current.running?'Stopping…':'Starting…';
    try {
      const value=await read('/api/ollama/server/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({action:current.running?'stop':'start'})});
      changing=false;render(value);root.dispatchEvent(new CustomEvent('ollama-runtime-changed',{detail:value}));await refresh();
    }catch(error){changing=false;status.textContent=error.message;toggle.disabled=false;}
  });
  save.addEventListener('click',async()=>{
    if(!defaults.value||save.disabled)return;
    save.disabled=true;feedback.textContent='Saving…';const selectedOrg=org.value;
    try {
      await read('/api/ai/configuration/',{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({default_model:defaults.value})});
      if(selectedOrg!==org.value)return;
      feedback.textContent='Default saved for this organization.';
      root.dispatchEvent(new CustomEvent('ollama-default-changed'));
    }catch(error){feedback.textContent=error.message;}
    finally{save.disabled=!current?.can_control;}
  });
  function fit() {
    if(!server.open)return;const panel=server.querySelector('.ai-runtime-panel'),anchor=server.getBoundingClientRect(),width=panel.getBoundingClientRect().width;
    panel.style.right='auto';panel.style.left=`${Math.max(12,Math.min(anchor.right-width,innerWidth-width-12))-anchor.left}px`;
  }
  window.addEventListener('resize',fit);
  server.addEventListener('toggle',()=>{if(server.open){fit();refresh();}});
  document.querySelector('#ai-ollama-refresh').addEventListener('click',refresh);
  document.addEventListener('click',event=>{if(!server.contains(event.target))server.open=false;});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&server.open){server.open=false;server.querySelector('summary').focus();}});
  org.addEventListener('change',()=>{++request;current=null;toggle.disabled=true;save.disabled=true;if(server.open)refresh();});
})();
