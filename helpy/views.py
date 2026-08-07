import calendar
import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control

from financeiro.models import AjusteSaldo, Essencial, Meta, SaldoExtra, Transacao
from financeiro.views import _periodo, projetar_fixas, sincronizar_fixas


@cache_control(max_age=0, no_cache=True, must_revalidate=True)
def serviceworker(request):
    return render(request, 'pwa/sw.js', content_type='application/javascript')


def manifest(request):
    return render(request, 'pwa/manifest.json', content_type='application/manifest+json')


def home(request):
    if request.user.is_authenticated:
        return redirect('painel')
    return render(request, 'home.html')


def _saldo_historico(usuario):
    """Saldo da conta.

    Sem âncora, é a soma de tudo que já foi lançado. Com âncora, parte do saldo
    real informado pelo usuário e soma só o que veio depois — o que aconteceu
    antes já está embutido naquele número. Lançamentos do próprio dia da âncora
    ficam de fora: o saldo do extrato naquela data já os contabiliza.
    """
    movimentos = Transacao.objects.filter(usuario=usuario)
    base = 0

    ancora = AjusteSaldo.vigente(usuario)
    if ancora:
        base = ancora.valor
        movimentos = movimentos.filter(data__gt=ancora.data)

    rec = movimentos.filter(tipo='receita').aggregate(t=Sum('valor'))['t'] or 0
    desp = movimentos.filter(tipo='despesa').aggregate(t=Sum('valor'))['t'] or 0
    return base + rec - desp


def _media_despesas_3m(usuario):
    """Retorna a média mensal de despesas dos últimos 3 meses completos."""
    hoje = date.today()
    totais = []
    for i in range(1, 4):
        m = hoje.month - i
        y = hoje.year
        while m <= 0:
            m += 12
            y -= 1
        inicio = date(y, m, 1)
        fim = date(y, m, calendar.monthrange(y, m)[1])
        total = (
            Transacao.objects
            .filter(usuario=usuario, tipo='despesa', data__gte=inicio, data__lte=fim)
            .aggregate(t=Sum('valor'))['t'] or 0
        )
        totais.append(float(total))
    return sum(totais) / 3


def _previsao_mensal_fixas(usuario):
    """Retorna (receita_prevista, despesa_prevista) exatas do mês atual:
    realizado até hoje + ocorrências futuras das fixas até o fim do mês
    (calculadas em memória, sem gravar no banco).

    Deve ser chamada após `sincronizar_fixas`."""
    hoje = date.today()
    inicio = date(hoje.year, hoje.month, 1)
    fim = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])

    def _realizado(tipo):
        return float(
            Transacao.objects
            .filter(usuario=usuario, tipo=tipo, data__gte=inicio, data__lte=hoje)
            .aggregate(t=Sum('valor'))['t'] or 0
        )

    rec = _realizado('receita')
    desp = _realizado('despesa')
    for p in projetar_fixas(usuario, hoje + timedelta(days=1), fim):
        if p['tipo'] == 'receita':
            rec += float(p['valor'])
        else:
            desp += float(p['valor'])
    return rec, desp


@login_required
def painel(request):
    hoje = date.today()
    sincronizar_fixas(request.user, limite=hoje)

    saldo_historico = _saldo_historico(request.user)
    saldos_extras = list(SaldoExtra.objects.filter(usuario=request.user))
    saldo_total = float(saldo_historico) + sum(float(se.valor) for se in saldos_extras)

    # Despesas do mês atual (1 a hoje)
    inicio_atual = date(hoje.year, hoje.month, 1)
    desp_mes_atual = float(
        Transacao.objects
        .filter(usuario=request.user, tipo='despesa', data__gte=inicio_atual, data__lte=hoje)
        .aggregate(t=Sum('valor'))['t'] or 0
    )
    avg_desp_3m = _media_despesas_3m(request.user)

    rec_prevista, desp_prevista = _previsao_mensal_fixas(request.user)
    economia_prevista = rec_prevista - desp_prevista

    tipos_saldo_extra = SaldoExtra.TIPO_CHOICES
    metas_resumo = list(Meta.objects.filter(usuario=request.user, concluida=False).select_related('categoria')[:4])

    salario_pendente = None
    ess_salario = None
    try:
        ess_sal = Essencial.objects.select_related('categoria', 'transacao_fixa').get(
            usuario=request.user, categoria__slug='salario', ativa=True,
        )
        if ess_sal.tipo_salario in ('comissao', 'fixo_comissao'):
            ess_salario = ess_sal          # permite registrar em qualquer dia
        if ess_sal.salario_pendente_hoje():
            salario_pendente = ess_sal
    except Essencial.DoesNotExist:
        pass

    return render(request, 'painel.html', {
        'saldo_historico': saldo_historico,
        'saldos_extras': saldos_extras,
        'saldo_total': saldo_total,
        'desp_mes_atual': desp_mes_atual,
        'avg_desp_3m': avg_desp_3m,
        'rec_prevista': rec_prevista,
        'desp_prevista': desp_prevista,
        'economia_prevista': economia_prevista,
        'tipos_saldo_extra': tipos_saldo_extra,
        'metas_resumo': metas_resumo,
        'salario_pendente': salario_pendente,
        'ess_salario': ess_salario,
        'hoje': hoje,
    })


@login_required
def resumo(request):
    ctx = _periodo(request)
    sincronizar_fixas(request.user, limite=min(ctx['fim'], date.today()))

    qs_rec = Transacao.objects.filter(
        usuario=request.user, tipo='receita',
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
    )
    qs_desp = Transacao.objects.filter(
        usuario=request.user, tipo='despesa',
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
    )

    total_receitas = qs_rec.aggregate(t=Sum('valor'))['t'] or 0
    total_despesas = qs_desp.aggregate(t=Sum('valor'))['t'] or 0
    saldo = total_receitas - total_despesas

    # Previsto: ocorrências futuras das fixas dentro do período (em memória)
    previstas = projetar_fixas(request.user, ctx['inicio'], ctx['fim'])
    rec_previsto = sum(p['valor'] for p in previstas if p['tipo'] == 'receita')
    desp_previsto = sum(p['valor'] for p in previstas if p['tipo'] == 'despesa')
    saldo_previsto = (total_receitas + rec_previsto) - (total_despesas + desp_previsto)

    transacoes = (
        Transacao.objects
        .filter(usuario=request.user, data__gte=ctx['inicio'], data__lte=ctx['fim'])
        .select_related('entidade', 'categoria')
        .order_by('-data', '-criado_em')
    )

    # Dados para gráfico 1: receita e despesa por semana do mês
    semanas_labels = []
    semanas_rec = []
    semanas_desp = []
    inicio = ctx['inicio']
    fim = ctx['fim']
    d = inicio
    while d <= fim:
        fim_semana = min(d + timedelta(days=6), fim)
        label = f'{d.day}/{d.month}–{fim_semana.day}/{fim_semana.month}'
        semanas_labels.append(label)
        r = float(qs_rec.filter(data__gte=d, data__lte=fim_semana).aggregate(t=Sum('valor'))['t'] or 0)
        e = float(qs_desp.filter(data__gte=d, data__lte=fim_semana).aggregate(t=Sum('valor'))['t'] or 0)
        semanas_rec.append(r)
        semanas_desp.append(e)
        d = fim_semana + timedelta(days=1)

    # Dados para gráfico 2: despesas por categoria
    cat_data = list(
        qs_desp
        .values('categoria__nome')
        .annotate(total=Sum('valor'))
        .order_by('-total')
    )
    cat_labels = [r['categoria__nome'] or 'Sem categoria' for r in cat_data]
    cat_valores = [float(r['total']) for r in cat_data]

    ctx.update({
        'total_receitas': total_receitas,
        'total_despesas': total_despesas,
        'saldo': saldo,
        'rec_previsto': rec_previsto,
        'desp_previsto': desp_previsto,
        'saldo_previsto': saldo_previsto,
        'tem_previsto': bool(previstas),
        'transacoes': transacoes,
        'semanas_labels': json.dumps(semanas_labels),
        'semanas_rec': json.dumps(semanas_rec),
        'semanas_desp': json.dumps(semanas_desp),
        'cat_labels': json.dumps(cat_labels),
        'cat_valores': json.dumps(cat_valores),
        'hoje': date.today(),
    })
    return render(request, 'resumo.html', ctx)
