from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from financeiro.models import Transacao
from financeiro.views import _periodo, sincronizar_fixas


def home(request):
    return render(request, 'home.html')


@login_required
def painel(request):
    ctx = _periodo(request)
    sincronizar_fixas(request.user, limite=ctx['fim'])

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

    recentes = (
        Transacao.objects
        .filter(usuario=request.user)
        .select_related('entidade', 'categoria')
        .order_by('-data', '-criado_em')[:8]
    )

    return render(request, 'painel.html', {
        **ctx,
        'total_receitas': total_receitas,
        'total_despesas': total_despesas,
        'saldo': saldo,
        'recentes': recentes,
    })
