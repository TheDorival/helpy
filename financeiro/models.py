import calendar
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models


CATALOGO_ESSENCIAIS = [
    # slug, nome, tipo, ícone, prioridade, variavel, frequencia, ordem, descricao
    ('salario',          'Salário',               'receita',  '💰', 'fundamental', False, 'mensal',  1,  'Principal fonte de renda mensal.'),
    ('freelance',        'Freelance / Renda extra','receita',  '🎯', 'opcional',    True,  'mensal',  2,  'Renda variável de projetos ou bicos.'),
    ('aluguel_recebido', 'Aluguel recebido',       'receita',  '🏘️', 'opcional',    False, 'mensal',  3,  'Renda de imóvel alugado.'),
    ('bolsa',            'Bolsa / Auxílio',        'receita',  '📚', 'opcional',    False, 'mensal',  4,  'Bolsa de estudos, auxílio ou benefício.'),
    ('aluguel',          'Aluguel / Prestação',    'despesa',  '🏠', 'fundamental', False, 'mensal',  1,  'Moradia — aluguel ou parcela de financiamento.'),
    ('energia',          'Energia elétrica',       'despesa',  '⚡', 'fundamental', True,  'mensal',  2,  'Conta de luz mensal.'),
    ('agua',             'Água / Saneamento',      'despesa',  '💧', 'fundamental', True,  'mensal',  3,  'Conta de água e saneamento.'),
    ('alimentacao',      'Alimentação / Mercado',  'despesa',  '🛒', 'fundamental', True,  'mensal',  4,  'Gastos com supermercado e refeições.'),
    ('transporte',       'Transporte',             'despesa',  '🚌', 'fundamental', True,  'mensal',  5,  'Transporte público, combustível ou aplicativo.'),
    ('internet',         'Internet',               'despesa',  '🌐', 'importante',  False, 'mensal',  6,  'Plano de internet residencial.'),
    ('telefone',         'Telefone / Celular',     'despesa',  '📱', 'importante',  False, 'mensal',  7,  'Plano de celular ou telefone fixo.'),
    ('saude',            'Plano de saúde',         'despesa',  '🏥', 'importante',  False, 'mensal',  8,  'Convênio médico ou odontológico.'),
    ('educacao',         'Faculdade / Escola',     'despesa',  '🎓', 'importante',  False, 'mensal',  9,  'Mensalidade de ensino.'),
    ('academia',         'Academia',               'despesa',  '🏋️', 'opcional',    False, 'mensal', 10,  'Mensalidade de academia ou esporte.'),
    ('streaming',        'Streaming',              'despesa',  '📺', 'opcional',    False, 'mensal', 11,  'Netflix, Disney+, HBO e outros.'),
    ('assinaturas',      'Assinaturas',            'despesa',  '🔔', 'opcional',    False, 'mensal', 12,  'Softwares, apps e serviços mensais.'),
]


class CategoriaEssencial(models.Model):
    TIPO_CHOICES = [('receita', 'Receita'), ('despesa', 'Despesa')]
    PRIORIDADE_CHOICES = [
        ('fundamental', 'Fundamental'),
        ('importante',  'Importante'),
        ('opcional',    'Opcional'),
    ]

    slug        = models.SlugField(unique=True)
    nome        = models.CharField(max_length=100)
    tipo        = models.CharField(max_length=10, choices=TIPO_CHOICES)
    icone       = models.CharField(max_length=10)
    prioridade  = models.CharField(max_length=12, choices=PRIORIDADE_CHOICES, default='importante')
    variavel    = models.BooleanField(default=False)
    frequencia  = models.CharField(max_length=20, default='mensal')
    ordem       = models.PositiveSmallIntegerField(default=0)
    descricao   = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Categoria essencial'
        verbose_name_plural = 'Categorias essenciais'
        ordering = ['tipo', 'prioridade', 'ordem']

    def __str__(self):
        return self.nome

    @classmethod
    def sincronizar_catalogo(cls):
        for slug, nome, tipo, icone, prioridade, variavel, frequencia, ordem, descricao in CATALOGO_ESSENCIAIS:
            cls.objects.update_or_create(
                slug=slug,
                defaults=dict(nome=nome, tipo=tipo, icone=icone, prioridade=prioridade,
                              variavel=variavel, frequencia=frequencia, ordem=ordem, descricao=descricao),
            )


class Essencial(models.Model):
    TIPO_SALARIO_CHOICES = [
        ('fixo',          'Salário fixo'),
        ('comissao',      'Comissão pura'),
        ('fixo_comissao', 'Fixo + Comissão'),
    ]
    FREQ_PAGAMENTO_CHOICES = [
        ('mensal',    'Mensal'),
        ('quinzenal', 'Quinzenal'),
        ('semanal',   'Semanal'),
    ]

    usuario            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='essenciais')
    categoria          = models.ForeignKey(CategoriaEssencial, on_delete=models.PROTECT, related_name='instancias')
    valor              = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_2            = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    dia_vencimento     = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Dia do mês (1–31)')
    data_inicio        = models.DateField()
    observacao         = models.TextField(blank=True, default='')
    ativa              = models.BooleanField(default=True)
    transacao_fixa     = models.OneToOneField(
        'TransacaoFixa', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='essencial',
    )
    transacao_fixa_2   = models.OneToOneField(
        'TransacaoFixa', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='essencial_2',
    )
    # Campos exclusivos do salário
    tipo_salario       = models.CharField(max_length=15, choices=TIPO_SALARIO_CHOICES, blank=True, default='')
    valor_fixo         = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    freq_pagamento     = models.CharField(max_length=10, choices=FREQ_PAGAMENTO_CHOICES, blank=True, default='mensal')
    dia_util           = models.BooleanField(default=False)
    dia_vencimento_2   = models.PositiveSmallIntegerField(null=True, blank=True)
    dia_util_2         = models.BooleanField(default=False)
    ultimo_registro    = models.DateField(null=True, blank=True)
    criado_em          = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Essencial'
        verbose_name_plural = 'Essenciais'
        unique_together = ('usuario', 'categoria')
        ordering = ['categoria__tipo', 'categoria__prioridade', 'categoria__ordem']

    def __str__(self):
        return f'{self.categoria.nome} — {self.usuario}'

    @property
    def nome_display(self):
        return self.categoria.nome

    @property
    def valor_display(self):
        if self.categoria.variavel:
            return 'Variável'
        return self.valor

    @property
    def total_mensal(self):
        if self.freq_pagamento != 'quinzenal':
            return self.valor or Decimal('0')
        v1 = self.valor or Decimal('0')
        v2 = self.valor_2 or v1
        return v1 + v2

    def salario_pendente_hoje(self):
        """True se hoje é dia de recebimento e a comissão ainda não foi registrada."""
        if self.categoria.slug != 'salario' or self.tipo_salario == 'fixo':
            return False
        if not self.dia_vencimento or not self.ativa:
            return False
        from datetime import date
        hoje = date.today()

        # Constrói o conjunto de datas/dias válidos para hoje
        dias_datas = set()   # date objects (dia_util)
        dias_fixos = set()   # day-of-month ints

        regra = getattr(self.usuario, 'regra_dia_util', REGRA_DIA_UTIL_PADRAO)

        def _add_dia(n, util):
            if util:
                d = _nth_business_day(hoje.year, hoje.month, n, regra)
                if d:
                    dias_datas.add(d)
            else:
                dias_fixos.add(n)

        _add_dia(self.dia_vencimento, self.dia_util)
        if self.freq_pagamento == 'quinzenal' and self.dia_vencimento_2:
            _add_dia(self.dia_vencimento_2, self.dia_util_2)

        if hoje not in dias_datas and hoje.day not in dias_fixos:
            return False

        return not (self.ultimo_registro and self.ultimo_registro == hoje)


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


# ── Bolsos ────────────────────────────────────────────────────────────────────
# De onde o dinheiro saiu ou para onde entrou. Sem isso, uma gratificação em
# espécie infla o saldo bancário e um gasto de vale o derruba — e a conferência
# contra o extrato, que é o que garante que a importação está íntegra, quebra.
CONTA_CHOICES = [
    ('banco',    'Conta bancária'),
    ('dinheiro', 'Dinheiro'),
    ('vale',     'Vale alimentação/refeição'),
    ('outro',    'Outro'),
]

# Vale só compra comida: somar com o resto dá um total que não existe na prática
CONTAS_RESTRITAS = frozenset({'vale'})


def conta_e_restrita(conta):
    return conta in CONTAS_RESTRITAS


def _campo_conta(ajuda):
    return models.CharField(max_length=10, choices=CONTA_CHOICES, default='banco',
                            db_index=True, help_text=ajuda)


class Transacao(models.Model):
    TIPO_CHOICES = [('receita', 'Receita'), ('despesa', 'Despesa')]

    usuario   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transacoes')
    tipo      = models.CharField(max_length=10, choices=TIPO_CHOICES)
    conta     = _campo_conta('Bolso de onde o dinheiro saiu ou entrou.')
    entidade  = models.ForeignKey(Entidade, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes')
    descricao = models.CharField(max_length=200, blank=True, default='')   # legado / fallback
    valor     = models.DecimalField(max_digits=12, decimal_places=2)
    data      = models.DateField()
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes')
    observacao = models.TextField(blank=True, default='')
    fitid      = models.CharField(max_length=120, blank=True, default='', db_index=True,
                                  help_text='ID único do lançamento no extrato importado (OFX).')
    importacao = models.ForeignKey('ImportacaoExtrato', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='transacoes')
    origem_fixa = models.ForeignKey('TransacaoFixa', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='ocorrencias',
                                    help_text='Recorrente que gerou esta transação.')
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
    conta          = _campo_conta('Bolso que as ocorrências desta recorrente vão usar.')
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
    dia_util_n     = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Se preenchido, cai sempre no N-ésimo dia útil do mês.',
    )
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

    MESES_POR_FREQUENCIA = {
        'mensal': 1, 'bimestral': 2, 'trimestral': 3, 'semestral': 6, 'anual': 12,
    }

    def avancar(self, data, regra=None):
        """Próxima ocorrência depois de `data`.

        Com `dia_util_n`, cada mês cai no N-ésimo dia útil (que muda de mês para
        mês); caso contrário mantém o dia do mês da data de início.
        """
        meses = self.MESES_POR_FREQUENCIA.get(self.frequencia)
        if self.dia_util_n and meses:
            total = data.year * 12 + (data.month - 1) + meses
            ano, mes = total // 12, total % 12 + 1
            alvo = _nth_business_day(ano, mes, self.dia_util_n,
                                     regra or self._regra_dia_util())
            if alvo:
                return alvo
        return _avancar_data(data, self.frequencia, self.intervalo_dias, self.data_inicio.day)

    def _regra_dia_util(self):
        return getattr(self.usuario, 'regra_dia_util', REGRA_DIA_UTIL_PADRAO) or REGRA_DIA_UTIL_PADRAO

    def proxima_data(self):
        base = self.ultima_geracao
        d = self.avancar(base) if base else self.data_inicio
        if self.data_fim and d > self.data_fim:
            return None
        return d


FERIADOS_FIXOS = (
    (1, 1),    # Confraternização Universal
    (4, 21),   # Tiradentes
    (5, 1),    # Dia do Trabalho
    (9, 7),    # Independência
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamação da República
    (11, 20),  # Consciência Negra (nacional desde 2024)
    (12, 25),  # Natal
)


def _pascoa(ano):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    from datetime import date
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_nacionais(ano):
    """Feriados nacionais brasileiros do ano, incluindo os móveis."""
    from datetime import date, timedelta
    dias = {date(ano, m, d) for m, d in FERIADOS_FIXOS}
    pascoa = _pascoa(ano)
    dias.update({
        pascoa - timedelta(days=48),  # segunda de carnaval
        pascoa - timedelta(days=47),  # terça de carnaval
        pascoa - timedelta(days=2),   # sexta-feira santa
        pascoa + timedelta(days=60),  # corpus christi
    })
    return dias


REGRA_DIA_UTIL_PADRAO = 'com_feriados'


def _eh_dia_util(d, regra, feriados):
    if regra == 'sem_feriados':          # seg–sex, feriados contam como dia útil
        return d.weekday() < 5
    if regra == 'clt':                   # exclui domingos e feriados; sábado conta
        return d.weekday() != 6 and d not in feriados
    return d.weekday() < 5 and d not in feriados   # com_feriados (padrão)


def _nth_business_day(year, month, n, regra=REGRA_DIA_UTIL_PADRAO):
    """Data do N-ésimo dia útil do mês, conforme a regra escolhida pelo usuário."""
    from datetime import date
    feriados = feriados_nacionais(year)
    day, count = 1, 0
    while True:
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if _eh_dia_util(d, regra, feriados):
            count += 1
            if count == n:
                return d
        day += 1


def _data_parcela(data_inicio, offset_meses):
    """Retorna data_inicio + offset_meses meses, ancorando no dia original."""
    from datetime import date
    total = data_inicio.year * 12 + (data_inicio.month - 1) + offset_meses
    ano, mes = total // 12, total % 12 + 1
    dia = min(data_inicio.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def _avancar_data(data, frequencia, intervalo_dias=None, dia_alvo=None):
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
    # usa o dia original (data_inicio.day) para evitar drift em meses curtos
    dia = min(dia_alvo or data.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


class Emprestimo(models.Model):
    TIPO_CHOICES = [('tomado', 'Tomado'), ('concedido', 'Concedido')]
    AMORTIZACAO_CHOICES = [('price', 'Tabela Price'), ('sac', 'SAC')]

    usuario          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='emprestimos')
    tipo             = models.CharField(max_length=10, choices=TIPO_CHOICES)
    entidade         = models.ForeignKey(Entidade, on_delete=models.SET_NULL, null=True, blank=True, related_name='emprestimos')
    descricao        = models.CharField(max_length=200, blank=True, default='')
    valor_total      = models.DecimalField(max_digits=12, decimal_places=2)
    n_parcelas       = models.PositiveIntegerField()
    taxa_juros       = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    tipo_amortizacao = models.CharField(max_length=10, choices=AMORTIZACAO_CHOICES, blank=True, default='')
    data_inicio      = models.DateField()
    observacao       = models.TextField(blank=True, default='')
    criado_em        = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Empréstimo'
        verbose_name_plural = 'Empréstimos'
        ordering = ['-criado_em']

    def __str__(self):
        nome = self.entidade.nome if self.entidade_id else (self.descricao or '—')
        return f'{self.get_tipo_display()} — {nome} — R$ {self.valor_total}'

    @property
    def nome_display(self):
        if self.entidade_id:
            return self.entidade.nome
        return self.descricao or '—'

    @property
    def com_juros(self):
        return bool(self.taxa_juros)

    def gerar_parcelas(self):
        n = self.n_parcelas
        pv = self.valor_total
        parcelas = []

        if self.taxa_juros:
            r = Decimal(str(self.taxa_juros)) / Decimal('100')
            saldo = pv

            if self.tipo_amortizacao == 'sac':
                principal_base = (pv / n).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                for i in range(n):
                    juros = (saldo * r).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    principal = saldo if i == n - 1 else principal_base
                    valor = principal + juros
                    parcelas.append(ParcelaEmprestimo(
                        emprestimo=self, numero=i + 1,
                        data_vencimento=_data_parcela(self.data_inicio, i),
                        valor=valor, valor_principal=principal, valor_juros=juros,
                    ))
                    saldo -= principal
            else:  # price
                r_f = float(r)
                pmt_f = float(pv) * r_f / (1 - (1 + r_f) ** -n)
                pmt = Decimal(str(round(pmt_f, 2)))
                for i in range(n):
                    juros = (saldo * r).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    if i == n - 1:
                        principal = saldo
                        valor = principal + juros
                    else:
                        principal = pmt - juros
                        valor = pmt
                    parcelas.append(ParcelaEmprestimo(
                        emprestimo=self, numero=i + 1,
                        data_vencimento=_data_parcela(self.data_inicio, i),
                        valor=valor, valor_principal=principal, valor_juros=juros,
                    ))
                    saldo -= principal
        else:
            valor_base = (pv / n).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            for i in range(n):
                valor = (pv - valor_base * (n - 1)) if i == n - 1 else valor_base
                parcelas.append(ParcelaEmprestimo(
                    emprestimo=self, numero=i + 1,
                    data_vencimento=_data_parcela(self.data_inicio, i),
                    valor=valor, valor_principal=valor, valor_juros=Decimal('0'),
                ))

        ParcelaEmprestimo.objects.bulk_create(parcelas)

    def criar_parcelas_personalizadas(self, datas, valores):
        from datetime import datetime
        parcelas = []
        for i, (data_str, valor_str) in enumerate(zip(datas, valores)):
            data = datetime.strptime(data_str.strip(), '%Y-%m-%d').date()
            valor = Decimal(str(valor_str).replace(',', '.').strip())
            parcelas.append(ParcelaEmprestimo(
                emprestimo=self, numero=i + 1,
                data_vencimento=data, valor=valor,
                valor_principal=valor, valor_juros=Decimal('0'),
            ))
        ParcelaEmprestimo.objects.bulk_create(parcelas)


class ParcelaEmprestimo(models.Model):
    emprestimo      = models.ForeignKey(Emprestimo, on_delete=models.CASCADE, related_name='parcelas')
    numero          = models.PositiveIntegerField()
    data_vencimento = models.DateField()
    valor           = models.DecimalField(max_digits=12, decimal_places=2)
    valor_principal = models.DecimalField(max_digits=12, decimal_places=2)
    valor_juros     = models.DecimalField(max_digits=12, decimal_places=2)
    paga            = models.BooleanField(default=False)
    data_pagamento  = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Parcela de empréstimo'
        verbose_name_plural = 'Parcelas de empréstimo'
        ordering = ['numero']


class Meta(models.Model):
    TIPO_CHOICES = [
        ('economia',     'Economia'),
        ('limite_gasto', 'Limite de gasto'),
        ('receita',      'Meta de receita'),
    ]

    usuario     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='metas')
    nome        = models.CharField(max_length=150)
    tipo        = models.CharField(max_length=15, choices=TIPO_CHOICES)
    valor_alvo  = models.DecimalField(max_digits=12, decimal_places=2)
    ajuste      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    categoria   = models.ForeignKey('Categoria', on_delete=models.SET_NULL, null=True, blank=True, related_name='metas')
    data_inicio = models.DateField()
    data_fim    = models.DateField(null=True, blank=True)
    observacao  = models.TextField(blank=True, default='')
    concluida   = models.BooleanField(default=False)
    criado_em   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Meta'
        verbose_name_plural = 'Metas'
        ordering = ['concluida', '-criado_em']

    def __str__(self):
        return self.nome

    def valor_atual(self):
        from django.db.models import Sum
        from datetime import date
        hoje = date.today()
        fim = min(self.data_fim, hoje) if self.data_fim else hoje
        inicio = self.data_inicio

        if self.tipo in ('economia', 'receita'):
            total = (
                Transacao.objects
                .filter(usuario=self.usuario, tipo='receita', data__gte=inicio, data__lte=fim)
                .aggregate(t=Sum('valor'))['t'] or 0
            )
        else:  # limite_gasto
            qs = Transacao.objects.filter(
                usuario=self.usuario, tipo='despesa',
                data__gte=inicio, data__lte=fim,
            )
            if self.categoria_id:
                qs = qs.filter(categoria_id=self.categoria_id)
            total = qs.aggregate(t=Sum('valor'))['t'] or 0

        return Decimal(str(total)) + self.ajuste

    def progresso_pct(self):
        alvo = float(self.valor_alvo)
        if alvo <= 0:
            return 0
        return min(round(float(self.valor_atual()) / alvo * 100, 1), 200)

    def dias_restantes(self):
        from datetime import date
        if not self.data_fim:
            return None
        return (self.data_fim - date.today()).days

    def status_cor(self):
        """Retorna 'green', 'amber' ou 'red' para a barra de progresso."""
        pct = self.progresso_pct()
        if self.tipo == 'limite_gasto':
            if pct >= 100:
                return 'red'
            if pct >= 80:
                return 'amber'
            return 'green'
        else:
            if pct >= 100:
                return 'green'
            if pct >= 50:
                return 'accent'
            return 'red'


class ImportacaoExtrato(models.Model):
    FORMATO_CHOICES = [('ofx', 'OFX'), ('csv', 'CSV')]

    usuario      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='importacoes')
    arquivo_nome = models.CharField(max_length=255)
    formato      = models.CharField(max_length=4, choices=FORMATO_CHOICES, default='ofx')
    banco        = models.CharField(max_length=100, blank=True, default='')
    conta        = models.CharField(max_length=60, blank=True, default='')
    periodo_inicio = models.DateField(null=True, blank=True)
    periodo_fim    = models.DateField(null=True, blank=True)
    n_importadas = models.PositiveIntegerField(default=0)
    n_ignoradas  = models.PositiveIntegerField(default=0)
    criado_em    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Importação de extrato'
        verbose_name_plural = 'Importações de extrato'
        ordering = ['-criado_em']

    def __str__(self):
        return f'{self.arquivo_nome} — {self.n_importadas} lançamento(s)'


class RegraCategoria(models.Model):
    TIPO_CHOICES = [
        ('ambos',   'Receitas e despesas'),
        ('receita', 'Só receitas'),
        ('despesa', 'Só despesas'),
    ]

    usuario   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='regras_categoria')
    termo     = models.CharField(
        max_length=120,
        help_text='Comparado com a linha inteira do extrato (operação + favorecido).',
    )
    categoria = models.ForeignKey(Categoria, null=True, blank=True,
                                  on_delete=models.CASCADE, related_name='regras')
    recorrente = models.ForeignKey('TransacaoFixa', null=True, blank=True,
                                   on_delete=models.CASCADE, related_name='regras',
                                   help_text='Lançamentos casados são conciliados com esta recorrente.')
    aplica_a  = models.CharField(max_length=8, choices=TIPO_CHOICES, default='ambos')
    entidade  = models.ForeignKey(Entidade, null=True, blank=True, on_delete=models.SET_NULL, related_name='regras')
    ativa     = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Regra de categorização'
        verbose_name_plural = 'Regras de categorização'
        ordering = ['termo']

    def __str__(self):
        destino = self.categoria or self.recorrente
        return f'{self.termo} → {destino}'

    def combina(self, descricao, tipo):
        if not self.ativa:
            return False
        if self.aplica_a != 'ambos' and self.aplica_a != tipo:
            return False
        return self.termo.strip().lower() in (descricao or '').lower()


class EventoVida(models.Model):
    TIPO_CHOICES = [
        ('carreira',   'Carreira'),
        ('educacao',   'Educação'),
        ('moradia',    'Moradia'),
        ('veiculo',    'Veículo'),
        ('viagem',     'Viagem'),
        ('saude',      'Saúde'),
        ('familia',    'Família'),
        ('financeiro', 'Conquista financeira'),
        ('outro',      'Outro'),
    ]

    ICONES = {
        'carreira': '💼', 'educacao': '🎓', 'moradia': '🏠', 'veiculo': '🚗',
        'viagem': '✈️', 'saude': '🏥', 'familia': '👨‍👩‍👧', 'financeiro': '🏆', 'outro': '📌',
    }

    usuario    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='eventos_vida')
    titulo     = models.CharField(max_length=150)
    tipo       = models.CharField(max_length=12, choices=TIPO_CHOICES, default='outro')
    data       = models.DateField()
    descricao  = models.TextField(blank=True, default='')
    valor      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    destaque   = models.BooleanField(default=False)
    transacao  = models.ForeignKey(
        'Transacao', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='eventos_vida',
        help_text='Transação financeira associada a este marco (opcional).',
    )
    criado_em  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Evento de vida'
        verbose_name_plural = 'Eventos de vida'
        ordering = ['-data', '-criado_em']

    def __str__(self):
        return f'{self.titulo} ({self.data:%d/%m/%Y})'

    @property
    def icone(self):
        return self.ICONES.get(self.tipo, '📌')

    @property
    def valor_efetivo(self):
        """Valor da transação vinculada, se houver; senão o valor informado."""
        if self.transacao_id and self.transacao:
            return self.transacao.valor
        return self.valor


class SaldoExtra(models.Model):
    TIPO_CHOICES = [
        ('conta',        'Conta'),
        ('investimento', 'Investimento'),
        ('cripto',       'Cripto'),
        ('vale',         'Vale alimentação/refeição'),
        ('outro',        'Outro'),
    ]

    usuario      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saldos_extras')
    nome         = models.CharField(max_length=100)
    valor        = models.DecimalField(max_digits=12, decimal_places=2)
    tipo         = models.CharField(max_length=15, choices=TIPO_CHOICES, default='outro')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Saldo extra'
        verbose_name_plural = 'Saldos extras'
        ordering = ['tipo', 'nome']

    def __str__(self):
        return f'{self.nome} — R$ {self.valor}'


class AjusteSaldo(models.Model):
    """Âncora: o saldo real da conta em uma data, conferido no extrato.

    O saldo do painel deixa de ser a soma de tudo que já foi lançado e passa a
    ser esta âncora mais o que se movimentou depois dela. Serve para quem começou
    a usar o app no meio do caminho ou para corrigir uma diferença acumulada sem
    inventar receita ou despesa — o ajuste não entra em médias, resumos nem
    gráficos de movimento.

    Vale sempre a âncora mais recente; as anteriores ficam como histórico.
    """

    usuario     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name='ajustes_saldo')
    conta       = _campo_conta('Bolso que este ajuste corrige.')
    data        = models.DateField(help_text='Data do saldo conferido no extrato')
    valor       = models.DecimalField(max_digits=12, decimal_places=2,
                                      help_text='Saldo real da conta nessa data')
    observacao  = models.CharField(max_length=200, blank=True)
    criado_em   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ajuste de saldo'
        verbose_name_plural = 'Ajustes de saldo'
        # Desempate por criado_em: dois ajustes no mesmo dia, vale o último feito
        ordering = ['-data', '-criado_em']
        indexes = [models.Index(fields=['usuario', 'conta', '-data'])]

    def __str__(self):
        return f'{self.get_conta_display()} {self.data:%d/%m/%Y} — R$ {self.valor}'

    @classmethod
    def vigente(cls, usuario, conta='banco'):
        """Âncora mais recente daquele bolso, ou None se ele nunca foi ajustado."""
        return cls.objects.filter(usuario=usuario, conta=conta).first()

    @classmethod
    def vigentes(cls, usuario):
        """Dicionário {conta: âncora} com a âncora vigente de cada bolso."""
        encontradas = {}
        for ajuste in cls.objects.filter(usuario=usuario):
            encontradas.setdefault(ajuste.conta, ajuste)   # ordering já traz a mais recente
        return encontradas
