from django import forms

from .models import Categoria, Transacao, TransacaoFixa


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


class TransacaoFixaForm(forms.ModelForm):
    class Meta:
        model = TransacaoFixa
        fields = ['tipo', 'descricao', 'valor', 'frequencia', 'data_inicio', 'data_fim', 'categoria', 'observacao']

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        date_widget = lambda: forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        self.fields['data_inicio'].widget = date_widget()
        self.fields['data_inicio'].input_formats = ['%Y-%m-%d']
        self.fields['data_fim'].widget = date_widget()
        self.fields['data_fim'].input_formats = ['%Y-%m-%d']
        self.fields['data_fim'].required = False
        self.fields['categoria'].required = False
        self.fields['observacao'].required = False
        if usuario:
            self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario)
        else:
            self.fields['categoria'].queryset = Categoria.objects.none()
