"""Reusable field vocabulary and starter compositions; no organization data."""
PREBUILT = [
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
