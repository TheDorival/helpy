from datetime import date

from django import forms

from .models import Categoria, Emprestimo, Entidade, Meta, Transacao, TransacaoFixa


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
        fields = ['tipo', 'descricao', 'entidade', 'valor', 'frequencia', 'intervalo_dias',
                  'data_inicio', 'data_fim', 'categoria', 'observacao']

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
        self.fields['intervalo_dias'].required = False
        if not self.instance.pk:
            self.fields['data_inicio'].initial = date.today()
        if usuario:
            self.fields['entidade'].queryset = Entidade.objects.filter(usuario=usuario)
            self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario)
        else:
            self.fields['entidade'].queryset = Entidade.objects.none()
            self.fields['categoria'].queryset = Categoria.objects.none()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('entidade') and not cleaned.get('descricao', '').strip():
            raise forms.ValidationError('Selecione uma entidade ou escolha "Outro" e informe uma descrição.')
        if cleaned.get('frequencia') == 'intervalo':
            intervalo = cleaned.get('intervalo_dias')
            if not intervalo or intervalo < 1:
                self.add_error('intervalo_dias', 'Informe o número de dias (mínimo 1).')
        return cleaned


class MetaForm(forms.ModelForm):
    class Meta:
        model = Meta
        fields = ['nome', 'tipo', 'valor_alvo', 'categoria', 'data_inicio', 'data_fim', 'observacao']

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
        if not self.instance.pk:
            self.fields['data_inicio'].initial = date.today()
        if usuario:
            self.fields['categoria'].queryset = Categoria.objects.filter(usuario=usuario, tipo='despesa')
        else:
            self.fields['categoria'].queryset = Categoria.objects.none()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('tipo') == 'limite_gasto' and not cleaned.get('categoria'):
            self.add_error('categoria', 'Selecione uma categoria para o limite de gasto.')
        data_inicio = cleaned.get('data_inicio')
        data_fim = cleaned.get('data_fim')
        if data_inicio and data_fim and data_fim <= data_inicio:
            self.add_error('data_fim', 'A data fim deve ser posterior à data de início.')
        return cleaned


class EmprestimoForm(forms.ModelForm):
    class Meta:
        model = Emprestimo
        fields = ['tipo', 'entidade', 'descricao', 'valor_total', 'n_parcelas',
                  'taxa_juros', 'tipo_amortizacao', 'data_inicio', 'observacao']

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['data_inicio'].widget = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        self.fields['data_inicio'].input_formats = ['%Y-%m-%d']
        self.fields['entidade'].required = False
        self.fields['descricao'].required = False
        self.fields['observacao'].required = False
        self.fields['taxa_juros'].required = False
        self.fields['tipo_amortizacao'].required = False
        if not self.instance.pk:
            self.fields['data_inicio'].initial = date.today()
        if usuario:
            self.fields['entidade'].queryset = Entidade.objects.filter(usuario=usuario)
        else:
            self.fields['entidade'].queryset = Entidade.objects.none()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('entidade') and not cleaned.get('descricao', '').strip():
            raise forms.ValidationError('Selecione uma entidade ou informe uma descrição.')
        taxa = cleaned.get('taxa_juros')
        if not taxa:
            cleaned['taxa_juros'] = None
            cleaned['tipo_amortizacao'] = ''
        elif not cleaned.get('tipo_amortizacao'):
            cleaned['tipo_amortizacao'] = 'price'
        return cleaned
