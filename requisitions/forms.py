from django import forms
from .models import Requisition, RequisitionItem, Item, Profile, Department
from django.forms import modelformset_factory
from django.contrib.auth.models import User


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        # REMOVE user & department (they are auto-filled in views)
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

        # Only show items that are in stock
        self.fields['item'].queryset = Item.objects.filter(stock__gt=0)

        # Make dropdown nicer
        self.fields['item'].label = "Select Item"
        self.fields['quantity'].label = "Quantity"


RequisitionItemFormSet = modelformset_factory(
    RequisitionItem,
    form=RequisitionItemForm,
    extra=1,
    can_delete=True,
)


# ==============================
# USER MANAGEMENT FORMS
# ==============================
class UserCreationForm(forms.ModelForm):
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    password_confirm = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        if password and password_confirm:
            if password != password_confirm:
                raise forms.ValidationError("Passwords do not match!")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['role']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-control'}),
        }
    

class StockForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'stock', 'sku', 'reorder_level']        