from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm

from .models import REGRA_DIA_UTIL_CHOICES, Usuario


class PreferenciasForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ('moeda', 'dia_corte', 'regra_dia_util')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['moeda'].label = 'Moeda padrão'
        self.fields['dia_corte'].label = 'Dia de corte do mês'
        self.fields['dia_corte'].widget = forms.NumberInput(attrs={'min': 1, 'max': 28})
        self.fields['regra_dia_util'].label = 'Contagem de dias úteis'
        # sem a opção vazia que o Django acrescenta
        self.fields['regra_dia_util'].choices = REGRA_DIA_UTIL_CHOICES


class AparenciaForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ('tema', 'cor_destaque', 'escala_fonte', 'reduzir_animacoes')

    def clean_cor_destaque(self):
        import re
        cor = (self.cleaned_data.get('cor_destaque') or '').strip().lower()
        if not re.fullmatch(r'#[0-9a-f]{6}', cor):
            raise forms.ValidationError('Cor inválida — use o formato #rrggbb.')
        return cor


class AlterarSenhaForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'autocomplete': 'off'})


class ExcluirContaForm(forms.Form):
    senha = forms.CharField(
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
        label='Confirme sua senha',
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_senha(self):
        senha = self.cleaned_data.get('senha')
        if not self.user.check_password(senha):
            raise forms.ValidationError('Senha incorreta.')
        return senha


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
