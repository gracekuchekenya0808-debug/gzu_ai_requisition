from django import forms
from .models import Requisition, RequisitionItem, Item
from django.forms import modelformset_factory


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        # ✅ REMOVE user & department (they are auto-filled in views)
        fields = ['request_date', 'notes']

        widgets = {
            'request_date': forms.DateInput(attrs={'type': 'date'}),
        }


class RequisitionItemForm(forms.ModelForm):
    class Meta:
        model = RequisitionItem
        fields = ['item', 'quantity']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ Only show items that are in stock
        self.fields['item'].queryset = Item.objects.filter(stock__gt=0)

        # ✅ Make dropdown nicer
        self.fields['item'].label = "Select Item"
        self.fields['quantity'].label = "Quantity"


RequisitionItemFormSet = modelformset_factory(
    RequisitionItem,
    form=RequisitionItemForm,
    extra=1,
    can_delete=True,
)