from django import template

register = template.Library()


@register.filter
def grouped_preview(fields):
    """Build the saved hierarchy without modifying the form definition."""
    root = []
    groups = {}
    for field in fields or []:
        parent = root
        path = list(field.get('ui_group_path', []))
        if field.get('ui_group'):
            path.append({'id':field['ui_group'], 'label':field.get('ui_group_label', 'Group'),
                         'layout':field.get('ui_group_layout', 'grid'),
                         'show_frame':field.get('ui_group_show_frame', True)})
        for group in path:
            key = group['id']
            if key not in groups:
                node = {'is_group':True, 'label':group['label'],
                        'layout':group.get('layout', 'grid'),
                        'show_frame':group.get('show_frame', True), 'children':[]}
                groups[key] = node
                parent.append(node)
            parent = groups[key]['children']
        parent.append({'is_group':False, 'field':field})
    return root
