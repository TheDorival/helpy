import calendar
import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from financeiro.models import Meta, SaldoExtra, Transacao, TransacaoFixa
from financeiro.views import _periodo, sincronizar_fixas


def home(request):
    return render(request, 'home.html')


def _saldo_historico(usuario):
    rec = Transacao.objects.filter(usuario=usuario, tipo='receita').aggregate(t=Sum('valor'))['t'] or 0
    desp = Transacao.objects.filter(usuario=usuario, tipo='despesa').aggregate(t=Sum('valor'))['t'] or 0
    return rec - desp


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
    """Retorna (receita_mensal_prevista, despesa_mensal_prevista) com base nas fixas ativas."""
    FREQ_OCC = {
        'diaria': 30, 'semanal': 4.33, 'quinzenal': 2,
        'mensal': 1, 'bimestral': 0.5, 'trimestral': 1/3,
        'semestral': 1/6, 'anual': 1/12,
    }
    rec = 0.0
    desp = 0.0
    for tf in TransacaoFixa.objects.filter(usuario=usuario, ativa=True):
        if tf.frequencia == 'intervalo' and tf.intervalo_dias:
            occ = 30 / tf.intervalo_dias
        else:
            occ = FREQ_OCC.get(tf.frequencia, 1)
        valor = float(tf.valor) * occ
        if tf.tipo == 'receita':
            rec += valor
        else:
            desp += valor
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
        'transacoes': transacoes,
        'semanas_labels': json.dumps(semanas_labels),
        'semanas_rec': json.dumps(semanas_rec),
        'semanas_desp': json.dumps(semanas_desp),
        'cat_labels': json.dumps(cat_labels),
        'cat_valores': json.dumps(cat_valores),
        'hoje': date.today(),
    })
    return render(request, 'resumo.html', ctx)
