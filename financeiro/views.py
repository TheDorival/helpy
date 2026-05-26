import calendar
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TransacaoForm
from .models import Transacao

MESES = [
    '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


def _periodo(request):
    hoje = date.today()
    try:
        mes = int(request.GET.get('mes', hoje.month))
        ano = int(request.GET.get('ano', hoje.year))
        if not (1 <= mes <= 12):
            mes, ano = hoje.month, hoje.year
    except (ValueError, TypeError):
        mes, ano = hoje.month, hoje.year

    mes_ant = (mes - 2) % 12 + 1
    ano_ant = ano - 1 if mes == 1 else ano
    mes_prox = mes % 12 + 1
    ano_prox = ano + 1 if mes == 12 else ano

    return {
        'mes': mes, 'ano': ano,
        'mes_nome': MESES[mes],
        'mes_anterior': {'mes': mes_ant, 'ano': ano_ant},
        'mes_proximo': {'mes': mes_prox, 'ano': ano_prox},
    }


@login_required
def receitas(request):
    ctx = _periodo(request)
    qs = Transacao.objects.filter(
        usuario=request.user, tipo='receita',
        data__month=ctx['mes'], data__year=ctx['ano'],
    )
    ctx['transacoes'] = qs
    ctx['total'] = qs.aggregate(t=Sum('valor'))['t'] or 0
    return render(request, 'financeiro/receitas.html', ctx)


@login_required
def despesas(request):
    ctx = _periodo(request)
    qs = Transacao.objects.filter(
        usuario=request.user, tipo='despesa',
        data__month=ctx['mes'], data__year=ctx['ano'],
    )
    ctx['transacoes'] = qs
    ctx['total'] = qs.aggregate(t=Sum('valor'))['t'] or 0
    return render(request, 'financeiro/despesas.html', ctx)


@login_required
def nova_receita(request):
    form = TransacaoForm(request.POST or None, usuario=request.user, tipo='receita')
    if request.method == 'POST' and form.is_valid():
        t = form.save(commit=False)
        t.usuario = request.user
        t.tipo = 'receita'
        t.save()
        return redirect('receitas')
    return render(request, 'financeiro/transacao_form.html', {
        'form': form, 'tipo': 'receita', 'titulo': 'Nova receita',
        'cancel_url': 'receitas',
    })


@login_required
def nova_despesa(request):
    form = TransacaoForm(request.POST or None, usuario=request.user, tipo='despesa')
    if request.method == 'POST' and form.is_valid():
        t = form.save(commit=False)
        t.usuario = request.user
        t.tipo = 'despesa'
        t.save()
        return redirect('despesas')
    return render(request, 'financeiro/transacao_form.html', {
        'form': form, 'tipo': 'despesa', 'titulo': 'Nova despesa',
        'cancel_url': 'despesas',
    })


@login_required
def editar_transacao(request, pk):
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    form = TransacaoForm(
        request.POST or None, instance=transacao,
        usuario=request.user, tipo=transacao.tipo,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('receitas' if transacao.tipo == 'receita' else 'despesas')
    return render(request, 'financeiro/transacao_form.html', {
        'form': form,
        'tipo': transacao.tipo,
        'titulo': f'Editar {transacao.get_tipo_display().lower()}',
        'cancel_url': 'receitas' if transacao.tipo == 'receita' else 'despesas',
        'transacao': transacao,
    })


@login_required
def excluir_transacao(request, pk):
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    tipo = transacao.tipo
    if request.method == 'POST':
        transacao.delete()
    return redirect('receitas' if tipo == 'receita' else 'despesas')
