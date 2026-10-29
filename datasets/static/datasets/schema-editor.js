/* Stable field IDs and explicit reference targets; server remains authoritative. */
(() => {
  const form = document.querySelector('#dataset-definition-form');
  if (!form) return;
  const json = form.querySelector('[name=schema]'), list = document.querySelector('#dataset-field-list');
  const error = document.querySelector('#dataset-schema-error'), raw = document.querySelector('#dataset-use-json');
  const lookups = JSON.parse(document.querySelector('#dataset-lookup-choices').textContent);
  const types = ['text','textarea','email','tel','number','select','radio','date','checkbox','rating','record_reference'];
  let base = {};
  function control(parent, caption, tag = 'input') {
    const label = document.createElement('label'); label.textContent = caption;
    const input = document.createElement(tag); label.append(input); parent.append(label); return input;
  }
  function add(field = {}) {
    const row = document.createElement('div'); row.className = 'schema-field';
    const main = document.createElement('div'); main.className = 'schema-field-main'; row.append(main);
    const label = control(main, 'Label'); label.value = field.label || '';
    const id = control(main, 'Field ID'); id.value = field.id || ''; id.required = true; id.pattern = '[A-Za-z][A-Za-z0-9_\x2d]{0,79}';
    label.addEventListener('input', () => { if (!id.dataset.edited) id.value = label.value.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,''); });
    id.addEventListener('input', () => { id.dataset.edited = '1'; }); if (field.id) id.dataset.edited = '1';
    const type = control(main, 'Type', 'select');
    types.forEach(kind => { const option = document.createElement('option'); option.value = kind; option.textContent = kind.replaceAll('_',' '); type.append(option); });
    type.value = field.type || 'text';
    const required = control(main, 'Required'); required.type = 'checkbox'; required.checked = !!field.required;
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary'; remove.textContent = 'Remove'; remove.onclick = () => row.remove(); main.append(remove);
    const extras = document.createElement('div'); extras.className = 'schema-field-options'; row.append(extras);
    const options = control(extras, 'Choices (comma separated)'); options.value = (field.options || []).join(', ');
    const min = control(extras, 'Minimum'); min.type = 'number'; min.step = 'any'; min.value = field.min ?? '';
    const max = control(extras, 'Maximum'); max.type = 'number'; max.step = 'any'; max.value = field.max ?? '';
    const lookup = control(extras, 'Lookup dataset', 'select');
    lookup.append(new Option('Choose a dataset', '')); lookups.forEach(item => lookup.append(new Option(item.name, item.id))); lookup.value = field.dataset_id || '';
    function refresh() { options.parentElement.hidden = !['select','radio'].includes(type.value); min.parentElement.hidden = max.parentElement.hidden = !['number','rating'].includes(type.value); lookup.parentElement.hidden = type.value !== 'record_reference'; }
    type.addEventListener('change', refresh); refresh();
    row.definition = () => {
      const value = {...field, id:id.value.trim(), label:label.value.trim(), type:type.value, required:required.checked};
      delete value.options; delete value.min; delete value.max; delete value.dataset_id;
      if (['select','radio'].includes(type.value)) value.options = options.value.split(',').map(s=>s.trim()).filter(Boolean);
      if (['number','rating'].includes(type.value)) { if(min.value !== '') value.min = Number(min.value); if(max.value !== '') value.max = Number(max.value); }
      if (type.value === 'record_reference') value.dataset_id = lookup.value;
      return value;
    };
    list.append(row);
  }
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
  raw.addEventListener('change', () => { list.querySelectorAll('input,select').forEach(input => input.disabled = raw.checked); });
})();
