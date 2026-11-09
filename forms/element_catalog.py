"""Reusable field vocabulary and starter compositions; no organization data."""
PREBUILT = [
    ('quantity', 'Quantity', 'Minus and plus buttons with a quantity between them'),
    ('text', 'Short answer', 'A single line of text'),
    ('textarea', 'Paragraph answer', 'A longer written response'),
    ('number', 'Number', 'A quantity with optional limits'),
    ('email', 'Email address', 'A validated email address'),
    ('tel', 'Phone number', 'A contact number'),
    ('select', 'Dropdown', 'Choose one from a compact list'),
    ('radio', 'Multiple choice', 'Choose one visible option'),
    ('multiselect', 'Checkboxes', 'Choose several options'),
    ('checkbox', 'Yes / no', 'A single boolean answer'),
    ('rating', 'Rating / scale', 'A numeric rating with bounds'),
    ('date', 'Date', 'Choose a calendar date'),
    ('time', 'Time', 'Choose a time of day'),
    ('file', 'File upload', 'Upload a document or image'),
    ('heading', 'Section heading', 'Display a title without collecting an answer'),
    ('paragraph', 'Text / instructions', 'Display explanatory text'),
    ('image', 'Image', 'Display an HTTPS image with alternative text'),
    ('item_cards', 'Library item cards', 'Current items, quantities and item-specific choices'),
]
STARTERS = {
    'order': {'name':'Menu order', 'description':'Choose current library items, their quantities and options, then add preparation notes.', 'schema':{'fields':[
        {'id':'menu_intro','label':'Choose your order','type':'heading'},
        {'id':'items','label':'Menu','type':'item_cards','required':True},
        {'id':'notes','label':'Preparation notes','type':'textarea','placeholder':'Allergies or special instructions'},
    ]}},
    'sandwich': {'name':'Sandwich card','description':'A fixed sandwich with quantity, spice preference and preparation notes.', 'schema':{'fields':[
        {'id':'item','label':'Sandwich','type':'heading'},
        {'id':'quantity','label':'Quantity','type':'number','min':1,'max':20,'required':True},
        {'id':'spice','label':'Spice level','type':'radio','options':['Mild','Medium','Hot'],'required':True},
        {'id':'notes','label':'Preparation notes','type':'textarea'},
    ]}},
    'event': {'name':'Event registration','description':'Contact details, session choice and accessibility requests.', 'schema':{'fields':[
        {'id':'name','label':'Full name','type':'text','required':True},
        {'id':'email','label':'Email','type':'email','required':True},
        {'id':'sessions','label':'Sessions','type':'multiselect','options':['Morning','Afternoon']},
        {'id':'accessibility','label':'Accessibility requests','type':'textarea'},
    ]}},
    'appointment': {'name':'Appointment request','description':'A reusable contact and scheduling group.', 'schema':{'fields':[
        {'id':'name','label':'Name','type':'text','required':True},
        {'id':'phone','label':'Phone','type':'tel','required':True},
        {'id':'date','label':'Preferred date','type':'date','required':True},
        {'id':'time','label':'Preferred time','type':'time'},
    ]}},
}

# Ready-to-use compositions; inventory values remain in each organization's Library.
STARTERS.update({
    'menu-card': {'name':'Restaurant menu cards','description':'Current Library menu items with images, names, descriptions, prices, quantities and item-specific choices.','schema':{'layout':'stack','fields':[
        {'id':'menu','label':'Choose menu items','type':'item_cards','required':True},
        {'id':'preparation_notes','label':'Preparation / allergy notes','type':'textarea','required':False},
    ]}},
    'contact': {'name':'Contact details','description':'A compact reusable contact group.','schema':{'layout':'grid','fields':[
        {'id':'full_name','label':'Full name','type':'text','required':True},
        {'id':'email','label':'Email address','type':'email','required':True},
        {'id':'phone','label':'Phone number','type':'tel','required':False},
    ]}},
    'delivery': {'name':'Delivery details','description':'Recipient, phone and delivery address.','schema':{'layout':'grid','fields':[
        {'id':'recipient','label':'Recipient name','type':'text','required':True},
        {'id':'phone','label':'Contact number','type':'tel','required':True},
        {'id':'address','label':'Delivery address','type':'textarea','required':True},
        {'id':'instructions','label':'Delivery instructions','type':'textarea','required':False},
    ]}},
    'feedback': {'name':'Feedback card','description':'Rating, comments and optional follow-up permission.','schema':{'layout':'grid','fields':[
        {'id':'rating','label':'Overall rating','type':'rating','min':1,'max':5,'required':True},
        {'id':'comments','label':'Your feedback','type':'textarea','required':False},
        {'id':'follow_up','label':'May we contact you about this feedback?','type':'checkbox','required':False},
    ]}},
})

STARTERS["quantity"] = {"name":"Quantity control", "description":"Choose a quantity with minus and plus buttons.", "schema":{"fields":[{"id":"quantity","label":"Quantity","type":"quantity","min":0,"max":50,"required":False}]}}

# Collection starters describe requests; acceptance/dispatch is a separate capability.
STARTERS.update({
    'journey': {'name': 'Journey request', 'description': 'Pickup, destination, preferred departure and passenger count. Confirmation is handled separately.', 'schema': {'layout': 'grid', 'fields': [
        {'id': 'pickup', 'label': 'Pickup location', 'type': 'text', 'required': True},
        {'id': 'destination', 'label': 'Destination', 'type': 'text', 'required': True},
        {'id': 'departure_date', 'label': 'Departure date', 'type': 'date', 'required': True},
        {'id': 'departure_time', 'label': 'Preferred departure time', 'type': 'time', 'required': True},
        {'id': 'passengers', 'label': 'Passengers', 'type': 'quantity', 'min': 1, 'max': 8, 'required': True},
        {'id': 'contact', 'label': 'Contact phone', 'type': 'tel', 'required': True},
    ]}},
    'reception': {'name': 'Reception check-in', 'description': 'A minimal arrival form for a reception desk. Customize service choices for your organization.', 'schema': {'layout': 'grid', 'fields': [
        {'id': 'visitor_name', 'label': 'Name', 'type': 'text', 'required': True},
        {'id': 'contact_phone', 'label': 'Contact phone', 'type': 'tel'},
        {'id': 'appointment_reference', 'label': 'Appointment reference, if available', 'type': 'text'},
        {'id': 'service', 'label': 'How can we help?', 'type': 'select', 'options': ['Scheduled appointment', 'New enquiry', 'Follow-up'], 'required': True},
        {'id': 'assistance', 'label': 'Assistance needed at reception', 'type': 'textarea'},
    ]}},
    'survey': {'name': 'Short survey', 'description': 'A simple opinion survey with a rating and open response.', 'schema': {'fields': [
        {'id': 'intro', 'label': 'Tell us about your experience', 'type': 'heading'},
        {'id': 'satisfaction', 'label': 'How satisfied are you?', 'type': 'rating', 'min': 1, 'max': 5, 'required': True},
        {'id': 'improvement', 'label': 'What could we improve?', 'type': 'textarea'},
        {'id': 'recommend', 'label': 'Would you recommend this service?', 'type': 'radio', 'options': ['Yes', 'No', 'Not sure'], 'required': True},
    ]}},
})

# Page sections use the same safe, editable fields as ordinary questions.
STARTERS.update({
    'welcome': {'name': 'Welcome / hero', 'description': 'Introduce your page with a prominent heading and a short explanation.', 'schema': {'fields': [
        {'id': 'title', 'type': 'heading', 'label': 'Welcome', 'layout_width': 'full'},
        {'id': 'intro', 'type': 'paragraph', 'label': 'Introduction', 'content': 'Tell visitors what this page is for and what they can do here.', 'layout_width': 'full'},
    ]}},
    'about': {'name': 'About this service', 'description': 'Explain what you offer before asking visitors for information.', 'schema': {'fields': [
        {'id': 'title', 'type': 'heading', 'label': 'About this service'},
        {'id': 'description', 'type': 'paragraph', 'label': 'Service overview', 'content': 'Describe your service, who it is for, and what is included.'},
    ]}},
    'steps': {'name': 'How it works', 'description': 'A three-step introduction to your collection process.', 'schema': {'layout': 'grid', 'fields': [
        {'id': 'choose', 'type': 'paragraph', 'label': '1. Choose', 'content': 'Choose the service or items you need.', 'layout_width': 'third'},
        {'id': 'details', 'type': 'paragraph', 'label': '2. Add details', 'content': 'Provide the information needed to handle your request.', 'layout_width': 'third'},
        {'id': 'send', 'type': 'paragraph', 'label': '3. Submit', 'content': 'Review your answers and submit your request.', 'layout_width': 'third'},
    ]}},
    'faq': {'name': 'Frequently asked questions', 'description': 'Two editable question-and-answer pairs for useful information above the submit button.', 'schema': {'fields': [
        {'id': 'question_one', 'type': 'heading', 'label': 'What should I prepare?'},
        {'id': 'answer_one', 'type': 'paragraph', 'label': 'Preparation', 'content': 'Explain which details visitors should have ready.'},
        {'id': 'question_two', 'type': 'heading', 'label': 'What happens after I submit?'},
        {'id': 'answer_two', 'type': 'paragraph', 'label': 'Next steps', 'content': 'Explain how requests are reviewed and how visitors will hear from you.'},
    ]}},
    'visit': {'name': 'Location & opening hours', 'description': 'Show your address, opening hours and arrival instructions. Replace the sample copy before publishing.', 'schema': {'layout': 'grid', 'fields': [
        {'id': 'location', 'type': 'paragraph', 'label': 'Where to find us', 'content': 'Add your address and directions here.', 'layout_width': 'half'},
        {'id': 'hours', 'type': 'paragraph', 'label': 'Opening hours', 'content': 'Add your opening days and hours here.', 'layout_width': 'half'},
        {'id': 'arrival', 'type': 'paragraph', 'label': 'Before you visit', 'content': 'Add any access or arrival instructions here.', 'layout_width': 'full'},
    ]}},
    'service-request': {'name': 'Service enquiry', 'description': 'Let visitors choose a service and describe what they need. Customize the service choices.', 'schema': {'fields': [
        {'id': 'title', 'type': 'heading', 'label': 'How can we help?'},
        {'id': 'service', 'type': 'radio', 'label': 'Choose a service', 'options': ['General enquiry', 'Request a quote', 'Support'], 'required': True},
        {'id': 'details', 'type': 'textarea', 'label': 'Tell us what you need', 'required': True},
    ]}},
    'pickup': {'name': 'Pickup details', 'description': 'Collect a name and preferred collection time for takeaway orders or equipment pickup.', 'schema': {'layout': 'grid', 'fields': [
        {'id': 'name', 'type': 'text', 'label': 'Name for pickup', 'required': True},
        {'id': 'phone', 'type': 'tel', 'label': 'Contact phone', 'required': True},
        {'id': 'date', 'type': 'date', 'label': 'Preferred pickup date', 'required': True},
        {'id': 'time', 'type': 'time', 'label': 'Preferred pickup time', 'required': True},
        {'id': 'notice', 'type': 'paragraph', 'label': 'Pickup request', 'content': 'Your preferred time is a request. Please wait for confirmation before collecting.', 'layout_width': 'full'},
    ]}},
    'attachments': {'name': 'Supporting attachment', 'description': 'An optional document or image with a short explanation.', 'schema': {'fields': [
        {'id': 'attachment', 'type': 'file', 'label': 'Attach a supporting file'},
        {'id': 'description', 'type': 'textarea', 'label': 'Tell us about this file'},
    ]}},
    'closing': {'name': 'Before you submit', 'description': 'End your page with review instructions and clear next steps. This is shown before submission.', 'schema': {'fields': [
        {'id': 'title', 'type': 'heading', 'label': 'Ready to submit?'},
        {'id': 'review', 'type': 'paragraph', 'label': 'Review your details', 'content': 'Check your answers before submitting. Describe your response process and expected timing here.'},
    ]}},
})

def compose_page(name, description, sections):
    """Copy section fields into distinct groups without sharing mutable defaults."""
    from copy import deepcopy
    fields = []
    for index, key in enumerate(sections):
        section = STARTERS[key]
        prefix = f"section{index + 1}"
        copied = deepcopy(section['schema']['fields'])
        identifiers = {field['id']: f"{prefix}_{field['id']}" for field in copied}
        for field in copied:
            field['id'] = identifiers[field['id']]
            if field.get('visibleWhen'):
                field['visibleWhen']['field'] = identifiers[field['visibleWhen']['field']]
            field.update(ui_group=prefix, ui_group_label=section['name'],
                         ui_group_layout=section['schema'].get('layout', 'stack'))
        fields.extend(copied)
    return {'name': name, 'description': description, 'schema': {'fields': fields}}


PAGE_RECIPES = {
    'survey-page': ('Survey page', 'An introduction, short survey and review instructions.', ('welcome', 'survey', 'closing')),
    'service-page': ('Service request page', 'Explain your service, collect an enquiry and contact details, and answer common questions.', ('about', 'service-request', 'contact', 'faq')),
    'reception-page': ('Reception page', 'Arrival information and a reception check-in. Customize this for your front desk.', ('visit', 'reception')),
    'order-page': ('Order request page', 'Library items, pickup preferences and contact details. Pickup times require separate confirmation.', ('order', 'pickup')),
}
for page_key, (name, description, sections) in PAGE_RECIPES.items():
    STARTERS[page_key] = compose_page(name, description, sections)


# Separate navigation metadata from the editable section definitions.
STARTER_GROUPS = (
    ('Complete pages', tuple(PAGE_RECIPES)),
    ('Page content', ('welcome', 'about', 'steps', 'faq', 'visit', 'closing')),
    ('Contact & requests', ('contact', 'service-request', 'appointment', 'journey', 'reception', 'attachments')),
    ('Orders & collection', ('order', 'menu-card', 'sandwich', 'delivery', 'pickup', 'quantity')),
    ('Events & feedback', ('event', 'survey', 'feedback')),
)


def starter_groups():
    return [{'name': name, 'starters': [dict(STARTERS[key], key=key) for key in keys]}
            for name, keys in STARTER_GROUPS]
