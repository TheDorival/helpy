import calendar

from django.conf import settings
from django.db import models


class Categoria(models.Model):
    TIPO_CHOICES = [('receita', 'Receita'), ('despesa', 'Despesa')]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='categorias')
    nome    = models.CharField(max_length=100)
    tipo    = models.CharField(max_length=10, choices=TIPO_CHOICES)

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['nome']
        unique_together = ('usuario', 'nome', 'tipo')

    def __str__(self):
        return self.nome


class Entidade(models.Model):
    TIPO_CHOICES = [
        ('pessoa',  'Pessoa'),
        ('empresa', 'Empresa'),
        ('projeto', 'Projeto'),
        ('outro',   'Outro'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='entidades')
    nome    = models.CharField(max_length=150)
    tipo    = models.CharField(max_length=10, choices=TIPO_CHOICES, default='pessoa')
    notas   = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Entidade'
        verbose_name_plural = 'Entidades'
        ordering = ['tipo', 'nome']
        unique_together = ('usuario', 'nome', 'tipo')

    def __str__(self):
        return self.nome


class Transacao(models.Model):
    TIPO_CHOICES = [('receita', 'Receita'), ('despesa', 'Despesa')]

    usuario   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transacoes')
    tipo      = models.CharField(max_length=10, choices=TIPO_CHOICES)
    entidade  = models.ForeignKey(Entidade, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes')
    descricao = models.CharField(max_length=200, blank=True, default='')   # legado / fallback
    valor     = models.DecimalField(max_digits=12, decimal_places=2)
    data      = models.DateField()
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes')
    observacao = models.TextField(blank=True, default='')
    criado_em  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transação'
        verbose_name_plural = 'Transações'
        ordering = ['-data', '-criado_em']

    def __str__(self):
        return f'{self.nome_display} — R$ {self.valor}'

    @property
    def nome_display(self):
        if self.entidade_id:
            return self.entidade.nome
        return self.descricao or '—'


class TransacaoFixa(models.Model):
    TIPO_CHOICES = [('receita', 'Receita'), ('despesa', 'Despesa')]
    FREQUENCIA_CHOICES = [
        ('diaria',     'Diária'),
        ('semanal',    'Semanal'),
        ('quinzenal',  'Quinzenal'),
        ('mensal',     'Mensal'),
        ('bimestral',  'Bimestral'),
        ('trimestral', 'Trimestral'),
        ('semestral',  'Semestral'),
        ('anual',      'Anual'),
        ('intervalo',  'A cada N dias'),
    ]

    usuario        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transacoes_fixas')
    tipo           = models.CharField(max_length=10, choices=TIPO_CHOICES)
    entidade       = models.ForeignKey(Entidade, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes_fixas')
    descricao      = models.CharField(max_length=200, blank=True, default='')   # legado / fallback
    valor          = models.DecimalField(max_digits=12, decimal_places=2)
    categoria      = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes_fixas')
    frequencia     = models.CharField(max_length=20, choices=FREQUENCIA_CHOICES, default='mensal')
    intervalo_dias = models.PositiveIntegerField(null=True, blank=True)
    data_inicio    = models.DateField()
    data_fim       = models.DateField(null=True, blank=True)
    observacao     = models.TextField(blank=True, default='')
    ativa          = models.BooleanField(default=True)
    ultima_geracao = models.DateField(null=True, blank=True)
    criado_em      = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transação fixa'
        verbose_name_plural = 'Transações fixas'
        ordering = ['-criado_em']

    def __str__(self):
        nome = self.entidade.nome if self.entidade_id else (self.descricao or '—')
        return f'{self.get_tipo_display()} — {nome} ({self.get_frequencia_display()})'

    @property
    def nome_display(self):
        if self.entidade_id:
            return self.entidade.nome
        return self.descricao or '—'

    def proxima_data(self):
        base = self.ultima_geracao
        d = _avancar_data(base, self.frequencia, self.intervalo_dias) if base else self.data_inicio
        if self.data_fim and d > self.data_fim:
            return None
        return d


def _avancar_data(data, frequencia, intervalo_dias=None):
    from datetime import date, timedelta
    meses = {'mensal': 1, 'bimestral': 2, 'trimestral': 3, 'semestral': 6, 'anual': 12}
    if frequencia == 'diaria':
        return data + timedelta(days=1)
    if frequencia == 'semanal':
        return data + timedelta(weeks=1)
    if frequencia == 'quinzenal':
        return data + timedelta(days=15)
    if frequencia == 'intervalo':
        return data + timedelta(days=intervalo_dias or 1)
    n = meses.get(frequencia, 1)
    total = data.year * 12 + (data.month - 1) + n
    ano, mes = total // 12, total % 12 + 1
    dia = min(data.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)
