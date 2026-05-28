import csv
import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CategoriaForm, EntidadeForm, TransacaoFixaForm, TransacaoForm
from .models import Categoria, Entidade, Transacao, TransacaoFixa, _avancar_data

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
    sincronizar_fixas(request.user, limite=ctx['fim'])
    qs = Transacao.objects.filter(
        usuario=request.user, tipo='receita',
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
    ).select_related('entidade', 'categoria')
    ctx['transacoes'] = qs
    ctx['total'] = qs.aggregate(t=Sum('valor'))['t'] or 0
    return render(request, 'financeiro/receitas.html', ctx)


@login_required
def despesas(request):
    ctx = _periodo(request)
    sincronizar_fixas(request.user, limite=ctx['fim'])
    qs = Transacao.objects.filter(
        usuario=request.user, tipo='despesa',
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
    ).select_related('entidade', 'categoria')
    ctx['transacoes'] = qs
    ctx['total'] = qs.aggregate(t=Sum('valor'))['t'] or 0
    return render(request, 'financeiro/despesas.html', ctx)


def _entidades_ctx(usuario):
    """Retorna entidades agrupadas por tipo para uso nos templates."""
    from itertools import groupby
    qs = list(Entidade.objects.filter(usuario=usuario))
    grupos = {}
    for e in qs:
        grupos.setdefault(e.get_tipo_display(), []).append(e)
    return qs, grupos


@login_required
def nova_receita(request):
    entidades, _ = _entidades_ctx(request.user)
    form = TransacaoForm(request.POST or None, usuario=request.user, tipo='receita')
    if request.method == 'POST' and form.is_valid():
        t = form.save(commit=False)
        t.usuario = request.user
        t.tipo = 'receita'
        t.save()
        return redirect('receitas')
    return render(request, 'financeiro/transacao_form.html', {
        'form': form, 'tipo': 'receita', 'titulo': 'Nova receita',
        'cancel_url': 'receitas', 'entidades': entidades,
    })


@login_required
def nova_despesa(request):
    entidades, _ = _entidades_ctx(request.user)
    form = TransacaoForm(request.POST or None, usuario=request.user, tipo='despesa')
    if request.method == 'POST' and form.is_valid():
        t = form.save(commit=False)
        t.usuario = request.user
        t.tipo = 'despesa'
        t.save()
        return redirect('despesas')
    return render(request, 'financeiro/transacao_form.html', {
        'form': form, 'tipo': 'despesa', 'titulo': 'Nova despesa',
        'cancel_url': 'despesas', 'entidades': entidades,
    })


@login_required
def editar_transacao(request, pk):
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    entidades, _ = _entidades_ctx(request.user)
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
        'entidades': entidades,
    })


@login_required
def excluir_transacao(request, pk):
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    tipo = transacao.tipo
    if request.method == 'POST':
        transacao.delete()
    return redirect('receitas' if tipo == 'receita' else 'despesas')


def sincronizar_fixas(usuario, limite=None):
    """Gera todas as ocorrências pendentes de transações fixas até `limite` (padrão: hoje)."""
    ate = limite if limite is not None else date.today()
    for tf in TransacaoFixa.objects.filter(usuario=usuario, ativa=True).select_related('categoria', 'entidade'):
        proxima  = _avancar_data(tf.ultima_geracao, tf.frequencia, tf.intervalo_dias, tf.data_inicio.day) if tf.ultima_geracao else tf.data_inicio
        lim_fixa = min(ate, tf.data_fim) if tf.data_fim else ate

        novas, ultima = [], tf.ultima_geracao
        d = proxima
        while d <= lim_fixa:
            novas.append(Transacao(
                usuario=tf.usuario, tipo=tf.tipo,
                entidade=tf.entidade, descricao=tf.descricao,
                valor=tf.valor, data=d,
                categoria=tf.categoria, observacao=tf.observacao,
            ))
            ultima = d
            d = _avancar_data(d, tf.frequencia, tf.intervalo_dias, tf.data_inicio.day)

        if novas:
            Transacao.objects.bulk_create(novas)
            TransacaoFixa.objects.filter(pk=tf.pk).update(ultima_geracao=ultima)


def _mes_atras(hoje, n):
    """Primeiro dia do mês N meses antes do mês atual."""
    total = hoje.year * 12 + (hoje.month - 1) - n
    return date(total // 12, total % 12 + 1, 1)


PERIODOS = [
    ('3m',        'Últimos 3 meses'),
    ('6m',        'Últimos 6 meses'),
    ('1a',        'Último ano'),
    ('ano_atual', 'Ano atual'),
    ('tudo',      'Todo o período'),
]


@login_required
def graficos(request):
    sincronizar_fixas(request.user)
    hoje = date.today()
    periodo = request.GET.get('periodo', '6m')

    if periodo == '3m':
        inicio = _mes_atras(hoje, 2)
    elif periodo == '6m':
        inicio = _mes_atras(hoje, 5)
    elif periodo == '1a':
        inicio = _mes_atras(hoje, 11)
    elif periodo == 'ano_atual':
        inicio = date(hoje.year, 1, 1)
    else:
        inicio = None

    qs = Transacao.objects.filter(usuario=request.user)
    if inicio:
        qs = qs.filter(data__gte=inicio)

    tem_dados = qs.exists()

    if tem_dados:
        primeira = qs.order_by('data').values_list('data', flat=True).first()
        mes_ini = date(primeira.year, primeira.month, 1)
        mes_fim = date(hoje.year, hoje.month, 1)

        meses = []
        m = mes_ini
        while m <= mes_fim:
            meses.append(m)
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)

        def agg_mensal(tipo):
            result = {}
            for row in (qs.filter(tipo=tipo)
                          .values('data__year', 'data__month')
                          .annotate(t=Sum('valor'))):
                result[date(row['data__year'], row['data__month'], 1)] = float(row['t'])
            return result

        rec_mens = agg_mensal('receita')
        desp_mens = agg_mensal('despesa')

        mostrar_ano = len(meses) > 12
        labels = [MESES[m.month] + (f"/{str(m.year)[-2:]}" if mostrar_ano else '') for m in meses]
        rec_data  = [rec_mens.get(m, 0)  for m in meses]
        desp_data = [desp_mens.get(m, 0) for m in meses]

        saldo_data, saldo = [], 0
        for r, d in zip(rec_data, desp_data):
            saldo = round(saldo + r - d, 2)
            saldo_data.append(saldo)

        def agg_cat(tipo):
            rows = list(qs.filter(tipo=tipo)
                          .values('categoria__nome')
                          .annotate(t=Sum('valor'))
                          .order_by('-t'))
            return {
                'labels': [r['categoria__nome'] or 'Sem categoria' for r in rows],
                'data':   [float(r['t']) for r in rows],
            }

        cat_desp = agg_cat('despesa')
        cat_rec  = agg_cat('receita')
    else:
        labels = rec_data = desp_data = saldo_data = []
        cat_desp = cat_rec = {'labels': [], 'data': []}

    return render(request, 'financeiro/graficos.html', {
        'periodo':           periodo,
        'periodos':          PERIODOS,
        'labels':            json.dumps(labels),
        'rec_data':          json.dumps(rec_data),
        'desp_data':         json.dumps(desp_data),
        'saldo_data':        json.dumps(saldo_data),
        'cat_desp_labels':   json.dumps(cat_desp['labels']),
        'cat_desp_data':     json.dumps(cat_desp['data']),
        'cat_desp_count':    len(cat_desp['data']),
        'cat_rec_labels':    json.dumps(cat_rec['labels']),
        'cat_rec_data':      json.dumps(cat_rec['data']),
        'cat_rec_count':     len(cat_rec['data']),
        'simbolo':           request.user.simbolo_moeda,
        'tem_dados':         tem_dados,
    })


@login_required
def fixas(request):
    sincronizar_fixas(request.user)
    qs = TransacaoFixa.objects.filter(usuario=request.user).select_related('categoria')
    items = [{'obj': tf, 'proxima': tf.proxima_data()} for tf in qs]
    return render(request, 'financeiro/fixas.html', {'items': items})


@login_required
def nova_fixa(request):
    todas_cat = Categoria.objects.filter(usuario=request.user)
    form = TransacaoFixaForm(request.POST or None, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        tf = form.save(commit=False)
        tf.usuario = request.user
        tf.save()
        sincronizar_fixas(request.user)
        return redirect('fixas')
    return render(request, 'financeiro/transacao_fixa_form.html', {
        'form': form, 'todas_cat': todas_cat, 'titulo': 'Nova recorrente',
    })


@login_required
def editar_fixa(request, pk):
    tf = get_object_or_404(TransacaoFixa, pk=pk, usuario=request.user)
    todas_cat = Categoria.objects.filter(usuario=request.user)
    form = TransacaoFixaForm(request.POST or None, instance=tf, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.ultima_geracao = date.today()   # novas ocorrências usam os valores editados
        obj.save()
        return redirect('fixas')
    return render(request, 'financeiro/transacao_fixa_form.html', {
        'form': form, 'todas_cat': todas_cat,
        'titulo': 'Editar recorrente', 'obj': tf,
    })


@login_required
def excluir_fixa(request, pk):
    tf = get_object_or_404(TransacaoFixa, pk=pk, usuario=request.user)
    if request.method == 'POST':
        tf.delete()
    return redirect('fixas')


@login_required
def toggle_fixa(request, pk):
    tf = get_object_or_404(TransacaoFixa, pk=pk, usuario=request.user)
    if request.method == 'POST':
        tf.ativa = not tf.ativa
        tf.save(update_fields=['ativa'])
        if tf.ativa:
            sincronizar_fixas(request.user)
    return redirect('fixas')


# ── CATEGORIAS ────────────────────────────────────────────────────────────────

@login_required
def categorias(request):
    receita_cats = Categoria.objects.filter(usuario=request.user, tipo='receita')
    despesa_cats = Categoria.objects.filter(usuario=request.user, tipo='despesa')
    return render(request, 'financeiro/categorias.html', {
        'receita_cats': receita_cats,
        'despesa_cats': despesa_cats,
    })


def _cat_ctx(usuario):
    return {
        'receita_cats': Categoria.objects.filter(usuario=usuario, tipo='receita'),
        'despesa_cats': Categoria.objects.filter(usuario=usuario, tipo='despesa'),
    }


@login_required
def nova_categoria(request):
    form = CategoriaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        cat = form.save(commit=False)
        cat.usuario = request.user
        cat.save()
        return redirect('categorias')
    return render(request, 'financeiro/categoria_form.html', {
        'form': form, 'titulo': 'Nova categoria', **_cat_ctx(request.user),
    })


@login_required
def editar_categoria(request, pk):
    cat = get_object_or_404(Categoria, pk=pk, usuario=request.user)
    form = CategoriaForm(request.POST or None, instance=cat)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('categorias')
    return render(request, 'financeiro/categoria_form.html', {
        'form': form, 'titulo': 'Editar categoria', 'obj': cat, **_cat_ctx(request.user),
    })


@login_required
def excluir_categoria(request, pk):
    cat = get_object_or_404(Categoria, pk=pk, usuario=request.user)
    if request.method == 'POST':
        cat.delete()
    return redirect('categorias')


# ── ENTIDADES ──────────────────────────────────────────────────────────────────

@login_required
def entidades(request):
    qs = Entidade.objects.filter(usuario=request.user)
    grupos = {}
    for e in qs:
        grupos.setdefault(e.tipo, []).append(e)
    return render(request, 'financeiro/entidades.html', {
        'entidades': qs,
        'grupos': grupos,
    })


@login_required
def nova_entidade(request):
    form = EntidadeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        e = form.save(commit=False)
        e.usuario = request.user
        e.save()
        next_url = request.GET.get('next', 'entidades')
        return redirect(next_url)
    return render(request, 'financeiro/entidade_form.html', {
        'form': form, 'titulo': 'Nova entidade',
        'entidades': Entidade.objects.filter(usuario=request.user),
    })


@login_required
def editar_entidade(request, pk):
    ent = get_object_or_404(Entidade, pk=pk, usuario=request.user)
    form = EntidadeForm(request.POST or None, instance=ent)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('entidades')
    return render(request, 'financeiro/entidade_form.html', {
        'form': form, 'titulo': 'Editar entidade', 'obj': ent,
        'entidades': Entidade.objects.filter(usuario=request.user),
    })


@login_required
def excluir_entidade(request, pk):
    ent = get_object_or_404(Entidade, pk=pk, usuario=request.user)
    if request.method == 'POST':
        ent.delete()
    return redirect('entidades')


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
