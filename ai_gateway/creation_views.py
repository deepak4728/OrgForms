import json
import copy
import re
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from chat.throttling import ChatRateThrottle
from organizations.models import Organization, OrganizationMembership
from organizations.permissions import require_membership, require_form_manage
from forms.models import Catalog, CatalogItem, DynamicForm
from .models import AIConfiguration
from .creation import local_json, installed_models, clean_form_draft, ORG_SCHEMA, FORM_SCHEMA


class DraftRequest(serializers.Serializer):
    prompt = serializers.CharField(max_length=4000)
    model = serializers.CharField(required=False,allow_blank=True,max_length=256)
    think = serializers.BooleanField(required=False, allow_null=True, default=None)
    include_form = serializers.BooleanField(required=False,default=False)
    mode = serializers.ChoiceField(choices=['form','questions'],required=False,default='form')
    form_id = serializers.UUIDField(required=False,allow_null=True)
    current_form = serializers.DictField(required=False,default=dict)


def draft_error(error):
    if isinstance(error,ValidationError):
        return Response({'detail':' '.join(error.messages)},status=422)
    if isinstance(error,(ValueError,KeyError,TypeError)):
        return Response({'detail':'The local model returned an invalid draft. Try a more specific prompt.'},status=422)
    return Response({'detail':'Local Ollama is unavailable. Start it in AI Hub, choose an installed model and retry. No cloud fallback was used.'},status=503)


@api_view(['POST'])
@throttle_classes([ChatRateThrottle])
def library_draft(request, org_slug, kind):
    org = get_object_or_404(Organization, slug=org_slug, is_archived=False)
    require_membership(request.user, org, manage=True)
    serializer = DraftRequest(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if kind not in ('item', 'dataset'):
        return Response({'detail': 'Unsupported library draft.'}, status=404)
    item_schema = {'type': 'object', 'additionalProperties': False,
        'properties': {key: {'type': 'string'} for key in ('name', 'category', 'description', 'price')},
        'required': ['name', 'category', 'description', 'price']}
    system = ('Return JSON only. Draft an item from the request. Use empty strings for unspecified details; never invent a price.'
              if kind == 'item' else
              'Return JSON only. Draft a dataset definition with a title, description, purpose and fields. Use only requested information. Do not create records.')
    try:
        generated, model, thinking, reasoning_mode = local_json(data['prompt'], system, data.get('model'), item_schema if kind == 'item' else FORM_SCHEMA)
        if kind == 'item':
            if set(generated) != {'name', 'category', 'description', 'price'} or any(not isinstance(v, str) for v in generated.values()):
                raise ValidationError('The local model returned an invalid item draft.')
            if not generated['name'].strip() or len(generated['name']) > 200 or len(generated['category']) > 100 or len(generated['description']) > 2000:
                raise ValidationError('The item draft has invalid details.')
            # Require explicit user review and entry of prices; do not trust generated amounts.
            generated['price'] = ''
            draft = generated
        else:
            from datasets.services import validate_dataset_schema
            cleaned = clean_form_draft(generated)
            validate_dataset_schema({'fields': cleaned['fields']}, org)
            draft = {'name': cleaned['title'], 'description': cleaned['description'], 'schema': {'fields': cleaned['fields']}}
        return Response({'draft': draft, 'model': model, 'source': 'local-ollama'})
    except (ValidationError, ValueError, KeyError, TypeError, URLError, OSError) as error:
        return draft_error(error)


@api_view(['GET'])
def creation_models(request):
    default = settings.OLLAMA_DEFAULT_MODEL
    slug = request.query_params.get('org')
    if slug:
        org = get_object_or_404(Organization,slug=slug,is_archived=False)
        require_membership(request.user,org)
        default = AIConfiguration.for_organization(org).default_model or default
    try:
        names = installed_models()
        return Response({'models':names,'default':default if default in names else '', 'ollama_running':True})
    except (URLError,OSError,ValueError):
        return Response({'models':[],'default':'','ollama_running':False})


@api_view(['POST'])
@throttle_classes([ChatRateThrottle])
def organization_draft(request):
    serializer = DraftRequest(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    system = ('Extract organization details from the request and return one JSON object matching the supplied schema. '
              'Use the actual name after "called" or "named" as name; do not use the organization type as its name. '
              'Put a stated city or address in address. Describe the stated activity in description and purpose. '
              'Copy phone and email exactly; use empty strings for details not stated. Never invent contact details, people or permissions. '
              'Choose the closest allowed business_type, or generic if uncertain. '
              'Example: "a community library in Jaipur called Open Shelf that organizes book lending and reading events" '
              'means name Open Shelf, address Jaipur, description and purpose book lending and reading events, business_type education, and empty phone and email. ')
    system += 'Include initial_form: a small relevant form with 3–8 questions, each with a stable English id, short label, type and required boolean. Choice questions need options. ' if data['include_form'] else 'Do not include initial_form. '
    try:
        warnings = []
        schema = copy.deepcopy(ORG_SCHEMA)
        if data['include_form']:
            schema['required'].append('initial_form')
        else:
            schema['properties'].pop('initial_form')
        draft, model, thinking, reasoning_mode = local_json(data['prompt'],system,data.get('model'),schema)
        safe = {}
        for key,limit in [('name',200),('description',2000),('purpose',80)]:
            value = draft.get(key,'')
            if not isinstance(value,str) or (key=='name' and not value.strip()):
                raise ValidationError('The organization draft has invalid or missing details.')
            value = value.strip()
            if len(value)>limit:
                if key != 'purpose':
                    raise ValidationError('The organization draft has invalid or missing details.')
                value = value[:limit].rstrip()
                warnings.append('The purpose was shortened to fit. Please review it.')
            safe[key] = value
        # Small models sometimes invent an organization's purpose. Prefer the
        # user's explicit "for ..." phrase and otherwise retain only literal text.
        source = data['prompt']
        named = re.search(r"\b(?:called|named)\s+([^,;\n.!?]+?)(?=\s+(?:that|which|where|in|located|based|with|for)\b|[,;\n.!?]|$)", source, re.I)
        if named:
            safe['name'] = named.group(1).strip()[:200]
        stated_purposes = list(re.finditer(r"\bfor\s+([^.!?\n]{3,200})", source, re.I))
        if not stated_purposes:
            stated_purposes = list(re.finditer(r"\b(?:that|which)\s+(?:organizes?|provides?|manages?|offers?)\s+([^.!?\n]{3,200})", source, re.I))
        if stated_purposes:
            stated = re.split(r"\s+(?:located|based|situated|with|whose)\b", stated_purposes[-1].group(1), maxsplit=1, flags=re.I)[0].strip(' ,;')
            if stated:
                safe['description'] = stated[:2000]
                safe['purpose'] = stated[:80].rstrip()
                if len(stated) > 80:
                    warnings.append('The purpose was shortened to fit. Please review it.')
        else:
            for key in ('description', 'purpose'):
                if safe[key] and safe[key].casefold() not in source.casefold():
                    safe[key] = ''
            if not safe['description'] and not safe['purpose']:
                warnings.append('Add a description or purpose if needed; the prompt did not state one clearly.')
        # Only accept contact and location values that are grounded in the request.
        # A small local model may omit them, so extract unambiguous literal values too.
        prompt = data['prompt']
        emails = list(dict.fromkeys(re.findall(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w-])", prompt)))
        phones = list(dict.fromkeys(match.group().strip() for match in re.finditer(r"(?<![\w@])\+?\d[\d ()-]{7,20}\d(?![\w@])", prompt) if 8 <= sum(ch.isdigit() for ch in match.group()) <= 15))
        safe['email'] = emails[0] if len(emails) == 1 else ''
        safe['phone'] = phones[0] if len(phones) == 1 else ''
        if len(emails) > 1 or len(phones) > 1:
            warnings.append('Multiple contact details were supplied; choose the correct one in Details.')
        address = draft.get('address', '')
        safe['address'] = address.strip()[:200] if isinstance(address, str) and address.strip() and address.strip().casefold() in prompt.casefold() else ''
        if not safe['address']:
            location = re.search(r"\b(?:located|based|situated|sited)\s+(?:in|at)\s+([\w][\w .'-]{0,100}?)(?=\s+(?:with|and|for|that|which|where|whose)\b|[,;\n]|[.!?](?:\s|$)|$)", prompt, re.I)
            if not location:
                location = re.search(r"\bin\s+([\w][\w .'-]{0,100}?)(?=\s+(?:called|named|that|which|where|with|for)\b|[,;\n]|[.!?](?:\s|$)|$)", prompt, re.I)
            if location:
                safe['address'] = location.group(1).strip(' .')[:200]
        safe['business_type'] = draft.get('business_type','generic')
        if safe['business_type'] not in dict(Organization.TYPE_CHOICES):
            raise ValidationError('The model returned an unsupported organization category.')
        if data['include_form'] and isinstance(draft.get('initial_form'), dict) and not re.search(r'\b\d+[\s-]*(?:characters?|chars?|letters?)\b', data['prompt'], re.I):
            for field in draft['initial_form'].get('fields', []):
                if isinstance(field,dict): field.pop('max_length', None)
        initial = clean_form_draft(draft.get('initial_form'), warnings=warnings) if data['include_form'] else None
        return Response({'organization':safe,'initial_form':initial,'model':model,'thinking':thinking,'reasoning_mode':reasoning_mode,'warnings':warnings,'source':'local-ollama'})
    except (ValidationError,ValueError,KeyError,TypeError,URLError,OSError) as error:
        return draft_error(error)


@api_view(['POST'])
@throttle_classes([ChatRateThrottle])
def form_draft(request,org_slug):
    org = get_object_or_404(Organization,slug=org_slug,is_archived=False)
    membership = require_membership(request.user,org)
    serializer = DraftRequest(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data['mode']=='questions' and data.get('form_id'):
        require_form_manage(request.user,get_object_or_404(DynamicForm,pk=data['form_id'],organization=org))
    elif membership.role not in ('admin','manager'):
        return Response({'detail':'An organization admin or manager is required to draft forms.'},status=403)
    current = data['current_form']
    questions = current.get('questions',[])
    if not isinstance(questions,list) or len(json.dumps(current))>20000:
        return Response({'detail':'Current form context is too large or invalid.'},status=400)
    catalogs = list(Catalog.objects.filter(organization=org).order_by('pk').values('id','name')[:10]) if membership.role in ('admin','manager') else []
    catalog_ids = [catalog['id'] for catalog in catalogs]
    items = list(CatalogItem.objects.filter(catalog_id__in=catalog_ids, is_available=True).order_by('catalog_id','name').values('catalog_id','name','category')[:100])
    context = {'request':data['prompt'],'organization':{'name':org.name,'purpose':org.purpose,'description':org.description[:1000]},'current_questions':questions[:50], 'catalogs':catalogs, 'available_items':items}
    schema = copy.deepcopy(FORM_SCHEMA)
    if membership.role in ('admin','manager'):
        field_schema = schema['properties']['fields']['items']
        field_schema['properties']['type']['enum'].append('item_cards')
        field_schema['properties']['catalog_id'] = {'type':'integer'}
    system = 'Draft a relevant form as JSON: title, description, purpose, fields. Use 3–12 questions with stable English ids, labels, types and required booleans. Only ask for information needed by the request. Choice fields must have options. Do not invent organization facts, catalog items, dataset IDs, or permissions. '
    system += ' Set max_length only if the user explicitly requests a character limit. Use layout_width only as a display preference. Keep purpose under 120 characters. If the user requests catalog items, add one item_cards field tied to an available catalog id. Item cards show the catalog’s available items; never invent or create catalog items. Never invent phone numbers or identifiers as dropdown choices; use a text or telephone input. '
    if data['mode']=='questions':
        system += 'Only propose new questions, without repeating current questions or their ids. '
    try:
        generated, model, thinking, reasoning_mode = local_json(json.dumps(context,ensure_ascii=False),system,data.get('model') or AIConfiguration.for_organization(org).default_model,schema,think=data.get('think'))
        warnings = []
        generated = copy.deepcopy(generated)
        fields = generated.get('fields')
        wants_cards = bool(re.search(r'\bitem[\s-]*cards?\b', data['prompt'], re.I))
        if isinstance(fields, list) and wants_cards and membership.role in ('admin','manager'):
            if len(catalogs) > 1:
                matches = [c for c in catalogs if c['name'].casefold() in data['prompt'].casefold()]
                if len(matches) != 1:
                    raise ValidationError('Please name the organization catalog to use for item cards.')
                selected_catalog = matches[0]['id']
            else:
                selected_catalog = catalog_ids[0] if catalog_ids else None
            original_count = len(fields)
            item_names = {item['name'].strip().casefold() for item in items}
            fields[:] = [field for field in fields if not (
                isinstance(field, dict) and field.get('type') != 'item_cards' and (
                    re.match(r'^\s*(?:item[\s_-]*cards?|menu[\s_-]*items?|item\s*\d+\s*[:.\-])', str(field.get('label', '')), re.I)
                    or str(field.get('label', '')).strip().casefold() in item_names
                )
            )]
            if len(fields) < original_count:
                warnings.append('Replaced generated item choices with item cards from the organization catalog.')
            if not any(isinstance(field, dict) and field.get('type') == 'item_cards' for field in fields):
                used = {field.get('id') for field in fields if isinstance(field, dict)}
                candidate, suffix = 'items', 2
                while candidate in used:
                    candidate = f'items_{suffix}'
                    suffix += 1
                card = {'id':candidate,'label':'Items','type':'item_cards','required':False}
                if selected_catalog is not None:
                    card['catalog_id'] = selected_catalog
                fields.append(card)
            elif selected_catalog is not None:
                for field in fields:
                    if isinstance(field, dict) and field.get('type') == 'item_cards':
                        field['catalog_id'] = selected_catalog
        if isinstance(fields, list):
            # Never turn an inferred size into an unrequested input restriction.
            if not re.search(r'\b\d+[\s-]*(?:characters?|chars?|letters?)\b', data['prompt'], re.I):
                for field in fields:
                    if isinstance(field, dict): field.pop('max_length', None)
            for field in fields:
                if not isinstance(field, dict):
                    continue
                options = field.get('options')
                label = str(field.get('label',''))
                if field.get('type') in ('select','radio') and re.search(r'\b(?:phone|mobile|telephone)\b', label, re.I) and isinstance(options, list) and options and all(isinstance(item, str) and re.fullmatch(r'[\d\s()+-]{6,}', item) for item in options) and not all(item in data['prompt'] for item in options):
                    field['type'] = 'text' if re.search(r'\b(?:id|identifier)\b', label, re.I) else 'tel'
                    field.pop('options', None)
                    warnings.append('Replaced example phone-number choices with an input. Review this field.')
        if data['mode']=='questions' and isinstance(fields, list):
            # Ignore repeated labels and assign stable, unique IDs before schema validation.
            reserved_ids = {str(q.get('id','')) for q in questions if isinstance(q,dict)}
            known_labels = {' '.join(str(q.get('label','')).split()).casefold() for q in questions if isinstance(q,dict)}
            distinct = []
            skipped = 0
            for field in fields:
                if not isinstance(field,dict):
                    distinct.append(field)
                    continue
                label = ' '.join(str(field.get('label','')).split()).casefold()
                if label and label in known_labels:
                    skipped += 1
                    continue
                if label:
                    known_labels.add(label)
                raw_id = str(field.get('id',''))
                base = re.sub(r'[^A-Za-z0-9_-]+','_',raw_id).strip('_-') or 'question'
                if not base[0].isalpha(): base = 'question_' + base
                candidate, suffix = base[:80], 2
                while candidate in reserved_ids:
                    tail = f'_{suffix}'
                    candidate = base[:80-len(tail)] + tail
                    suffix += 1
                field['id'] = candidate
                reserved_ids.add(candidate)
                distinct.append(field)
            generated['fields'] = distinct
            fields = distinct
            if skipped:
                warnings.append(f'Skipped {skipped} repeated question(s).')
            if not fields:
                raise ValidationError('The model did not suggest any new questions. Try a more specific request.')
            if not isinstance(generated.get('title'),str) or not generated['title'].strip():
                generated['title'] = str(current.get('title') or 'Suggested questions')[:200]
            for key in ('description','purpose'):
                if not isinstance(generated.get(key),str): generated[key] = ''
        safe = clean_form_draft(generated, catalog_ids=catalog_ids if membership.role in ('admin','manager') else None, warnings=warnings)
        if any(field['type'] == 'item_cards' for field in safe['fields']):
            warnings.append('Item cards show all available items in the selected catalog. Review the catalog before publishing.' if catalog_ids else 'The catalog is empty. Add items before publishing.')
        request_text = data['prompt'].lower()
        alternative_contact = re.search(r'\b(?:id|identifier|identification)\b.{0,40}\bor\b.{0,40}\b(?:mobile|phone|telephone)\b|\b(?:mobile|phone|telephone)\b.{0,40}\bor\b.{0,40}\b(?:id|identifier|identification)\b', request_text)
        if alternative_contact or any(phrase in request_text for phrase in ('at least one', 'one of', 'either')):
            warnings.append('Review the required fields: choosing at least one of several fields is not yet enforced automatically.')
        if alternative_contact and not any(re.search(r'\b(?:id|identifier|identification)\b', field['label'], re.I) for field in safe['fields']):
            warnings.append('The draft may have omitted the ID option. Review or add it before saving.')
        return Response({'success':True,'form':safe,'model':model,'source':'local-ollama','thinking':thinking,'reasoning_mode':reasoning_mode,'warnings':warnings})
    except (ValidationError,ValueError,KeyError,TypeError,URLError,OSError) as error:
        return draft_error(error)


