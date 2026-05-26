from django import forms

from .models import Categoria, Transacao


class TransacaoForm(forms.ModelForm):
    class Meta:
        model = Transacao
        fields = ['descricao', 'valor', 'data', 'categoria', 'observacao']

    def __init__(self, *args, usuario=None, tipo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['data'].widget = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        self.fields['data'].input_formats = ['%Y-%m-%d']
        self.fields['observacao'].required = False
        self.fields['categoria'].required = False
        if usuario and tipo:
            self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario, tipo=tipo)
        else:
            self.fields['categoria'].queryset = Categoria.objects.none()
