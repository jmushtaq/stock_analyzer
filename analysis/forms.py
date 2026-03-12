from django import forms
from django.utils import timezone
from datetime import timedelta
from analysis.models import WhatIfScenario
from stocks.models import Symbol

class DateRangeForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')

        if start and end and start > end:
            raise forms.ValidationError("Start date must be before end date")

        return cleaned_data

class MovementAnalysisForm(DateRangeForm):
    threshold = forms.FloatField(
        min_value=0.1, max_value=50, initial=10,
        help_text="Minimum price movement percentage to detect"
    )
    min_volume_factor = forms.FloatField(
        min_value=1, max_value=10, initial=1.5,
        help_text="Minimum volume multiple vs average"
    )
    symbols = forms.ModelMultipleChoiceField(
        queryset=Symbol.objects.filter(is_active=True),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': 10})
    )

class VolatilityAnalysisForm(forms.Form):
    symbol = forms.ModelChoiceField(
        queryset=Symbol.objects.filter(is_active=True),
        required=True
    )
    period = forms.IntegerField(min_value=5, max_value=252, initial=30)
    include_sector = forms.BooleanField(required=False, initial=True)

class WhatIfForm(forms.ModelForm):
    class Meta:
        model = WhatIfScenario
        fields = ['name', 'description', 'symbols', 'start_date', 'end_date', 'rules', 'is_public']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'symbols': forms.SelectMultiple(attrs={'size': 15}),
            'rules': forms.Textarea(attrs={'rows': 10, 'class': 'font-monospace'}),
        }
        help_texts = {
            'rules': 'JSON format: {"entry": {"type": "price_drop", "threshold": -10}, "exit": {"type": "price_target", "target": 5}}'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['symbols'].queryset = Symbol.objects.filter(is_active=True).order_by('ticker')
        self.fields['start_date'].initial = timezone.now().date() - timedelta(days=365)
        self.fields['end_date'].initial = timezone.now().date()

