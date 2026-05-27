from datetime import date

from django import forms

from .models import Categoria, Entidade, Transacao, TransacaoFixa


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome', 'tipo']


class EntidadeForm(forms.ModelForm):
    class Meta:
        model = Entidade
        fields = ['nome', 'tipo', 'notas']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['notas'].required = False


class TransacaoForm(forms.ModelForm):
    class Meta:
        model = Transacao
        fields = ['entidade', 'descricao', 'valor', 'data', 'categoria', 'observacao']

    def __init__(self, *args, usuario=None, tipo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['data'].widget = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        self.fields['data'].input_formats = ['%Y-%m-%d']
        self.fields['observacao'].required = False
        self.fields['entidade'].required = False
        self.fields['descricao'].required = False
        self.fields['categoria'].required = False
        if not self.instance.pk:
            self.fields['data'].initial = date.today()
        if usuario:
            self.fields['entidade'].queryset = Entidade.objects.filter(usuario=usuario)
            if tipo:
                self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario, tipo=tipo)
            else:
                self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario)
        else:
            self.fields['entidade'].queryset = Entidade.objects.none()
            self.fields['categoria'].queryset = Categoria.objects.none()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('entidade') and not cleaned.get('descricao', '').strip():
            raise forms.ValidationError('Selecione uma entidade ou escolha "Outro" e informe uma descrição.')
        return cleaned


class TransacaoFixaForm(forms.ModelForm):
    class Meta:
        model = TransacaoFixa
        fields = ['tipo', 'descricao', 'entidade', 'valor', 'frequencia', 'data_inicio', 'data_fim', 'categoria', 'observacao']

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        date_widget = lambda: forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        self.fields['data_inicio'].widget = date_widget()
        self.fields['data_inicio'].input_formats = ['%Y-%m-%d']
        self.fields['data_fim'].widget = date_widget()
        self.fields['data_fim'].input_formats = ['%Y-%m-%d']
        self.fields['data_fim'].required = False
        self.fields['descricao'].required = False
        self.fields['entidade'].required = False
        self.fields['categoria'].required = False
        self.fields['observacao'].required = False
        if not self.instance.pk:
            self.fields['data_inicio'].initial = date.today()
        if usuario:
            self.fields['entidade'].queryset = Entidade.objects.filter(usuario=usuario)
            self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario)
        else:
            self.fields['entidade'].queryset = Entidade.objects.none()
            self.fields['categoria'].queryset = Categoria.objects.none()
