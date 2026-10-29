from django import forms
from .models import Department, OrganizationMembership
from forms.models import DynamicForm


class MembershipChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, membership):
        return membership.user.get_full_name() or membership.user.email or membership.user.username


class DepartmentForm(forms.ModelForm):
    members = MembershipChoices(queryset=OrganizationMembership.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)

    collections = forms.ModelMultipleChoiceField(queryset=DynamicForm.objects.none(), required=False, widget=forms.CheckboxSelectMultiple, label="Responsible for collections")

    class Meta:
        model = Department
        fields = ('name', 'description')
        widgets = {'description': forms.Textarea(attrs={'rows': 2, 'maxlength': 1000})}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organization = organization
        self.fields['description'].max_length = 1000
        self.fields['collections'].queryset = organization.forms.all()
        self.fields['members'].queryset = organization.memberships.select_related('user')
        if self.instance.pk and not self.is_bound:
            self.initial['collections'] = self.instance.stewardships.values_list('collection_id', flat=True)
            self.initial['members'] = self.instance.staff_assignments.values_list('membership_id', flat=True)

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if Department.objects.filter(organization=self.instance.organization, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('A department with this name already exists.')
        return name
