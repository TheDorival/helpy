import csv
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TransacaoForm
from .models import Transacao

MESES = [
    '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


def _periodo(request):
    hoje = date.today()
    dia_corte = getattr(request.user, 'dia_corte', 1)

    try:
        mes = int(request.GET.get('mes', 0))
        ano = int(request.GET.get('ano', 0))
    except (ValueError, TypeError):
        mes = ano = 0

    if not mes or not ano or not (1 <= mes <= 12):
        if hoje.day >= dia_corte:
            mes, ano = hoje.month, hoje.year
        else:
            mes = hoje.month - 1 if hoje.month > 1 else 12
            ano = hoje.year if hoje.month > 1 else hoje.year - 1

    inicio = date(ano, mes, dia_corte)
    mes_fim = mes % 12 + 1
    ano_fim = ano + 1 if mes == 12 else ano
    fim = date(ano_fim, mes_fim, dia_corte) - timedelta(days=1)

    mes_ant = (mes - 2) % 12 + 1
    ano_ant = ano - 1 if mes == 1 else ano
    mes_prox = mes % 12 + 1
    ano_prox = ano + 1 if mes == 12 else ano

    return {
        'mes': mes, 'ano': ano,
        'mes_nome': MESES[mes],
        'inicio': inicio,
        'fim': fim,
        'dia_corte': dia_corte,
        'mes_anterior': {'mes': mes_ant, 'ano': ano_ant},
        'mes_proximo': {'mes': mes_prox, 'ano': ano_prox},
    }


@login_required
def receitas(request):
    ctx = _periodo(request)
    qs = Transacao.objects.filter(
        usuario=request.user, tipo='receita',
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
    )
    ctx['transacoes'] = qs
    ctx['total'] = qs.aggregate(t=Sum('valor'))['t'] or 0
    return render(request, 'financeiro/receitas.html', ctx)


@login_required
def despesas(request):
    ctx = _periodo(request)
    qs = Transacao.objects.filter(
        usuario=request.user, tipo='despesa',
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
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


@login_required
def exportar_dados(request):
    simbolo = request.user.simbolo_moeda
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="helpy_transacoes.csv"'
    response.write('﻿')  # BOM para Excel reconhecer UTF-8

    writer = csv.writer(response)
    writer.writerow(['Tipo', 'Descrição', f'Valor ({simbolo})', 'Data', 'Categoria', 'Observação', 'Registrado em'])

    transacoes = (
        Transacao.objects
        .filter(usuario=request.user)
        .select_related('categoria')
        .order_by('-data', '-criado_em')
    )

    for t in transacoes:
        writer.writerow([
            t.get_tipo_display(),
            t.descricao,
            str(t.valor),
            t.data.strftime('%d/%m/%Y'),
            t.categoria.nome if t.categoria else '',
            t.observacao,
            t.criado_em.strftime('%d/%m/%Y %H:%M'),
        ])

    return response
