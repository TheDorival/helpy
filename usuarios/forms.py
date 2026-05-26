from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Usuario


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ('first_name', 'last_name', 'email', 'telefone', 'data_nascimento', 'bio', 'avatar')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
        self.fields['bio'].required = False
        self.fields['telefone'].required = False
        self.fields['data_nascimento'].required = False
        self.fields['avatar'].required = False
        self.fields['data_nascimento'].widget = forms.DateInput(
            attrs={'type': 'date'}, format='%Y-%m-%d'
        )
        self.fields['data_nascimento'].input_formats = ['%Y-%m-%d']


class CadastroForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = (
            'first_name',
            'last_name',
            'username',
            'email',
            'telefone',
            'data_nascimento',
            'password1',
            'password2',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
