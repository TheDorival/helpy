import csv
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (CategoriaForm, EmprestimoForm, EntidadeForm, EventoVidaForm, MetaForm,
                    RegraCategoriaForm, TransacaoFixaForm, TransacaoForm)
from .importacao import (ExtratoInvalido, conferencia_lancamentos, detectar_colunas, ler_csv,
                         meta_do_extrato, parse_csv, parse_linhas_caixa, parse_ofx)
from .models import (Categoria, CategoriaEssencial, Emprestimo, Entidade, Essencial, EventoVida,
                     ImportacaoExtrato, Meta, ParcelaEmprestimo, RegraCategoria, SaldoExtra,
                     Transacao, TransacaoFixa, _avancar_data, _data_parcela)

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


def _listagem_transacoes(request, tipo, template):
    ctx = _periodo(request)
    sincronizar_fixas(request.user, limite=min(ctx['fim'], date.today()))
    qs = Transacao.objects.filter(
        usuario=request.user, tipo=tipo,
        data__gte=ctx['inicio'], data__lte=ctx['fim'],
    ).select_related('entidade', 'categoria')
    ctx['transacoes'] = qs
    ctx['total'] = qs.aggregate(t=Sum('valor'))['t'] or 0

    previstas = projetar_fixas(request.user, ctx['inicio'], ctx['fim'], tipo=tipo)
    ctx['previstas'] = previstas
    ctx['total_previsto'] = sum(p['valor'] for p in previstas)
    ctx['total_geral'] = ctx['total'] + ctx['total_previsto']
    return render(request, template, ctx)


@login_required
def receitas(request):
    return _listagem_transacoes(request, 'receita', 'financeiro/receitas.html')


@login_required
def despesas(request):
    return _listagem_transacoes(request, 'despesa', 'financeiro/despesas.html')


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


def projetar_fixas(usuario, inicio, fim, tipo=None):
    """Retorna ocorrências FUTURAS (ainda não geradas) das fixas ativas entre
    `inicio` e `fim`, calculadas em memória — nada é gravado no banco.

    Deve ser chamada após `sincronizar_fixas`, para que `ultima_geracao`
    esteja atualizada e não haja sobreposição com transações já criadas.
    """
    itens = []
    qs = TransacaoFixa.objects.filter(usuario=usuario, ativa=True).select_related('categoria', 'entidade')
    if tipo:
        qs = qs.filter(tipo=tipo)

    for tf in qs:
        d = (_avancar_data(tf.ultima_geracao, tf.frequencia, tf.intervalo_dias, tf.data_inicio.day)
             if tf.ultima_geracao else tf.data_inicio)
        lim = min(fim, tf.data_fim) if tf.data_fim else fim
        guarda = 0
        while d <= lim and guarda < 500:
            if d >= inicio:
                itens.append({
                    'data': d,
                    'tipo': tf.tipo,
                    'nome_display': tf.nome_display,
                    'valor': tf.valor,
                    'categoria': tf.categoria,
                    'fixa': tf,
                })
            guarda += 1
            d = _avancar_data(d, tf.frequencia, tf.intervalo_dias, tf.data_inicio.day)

    itens.sort(key=lambda x: x['data'])
    return itens


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
    ('prox_3m',   'Próximos 3 meses'),
    ('prox_6m',   'Próximos 6 meses'),
]


@login_required
def graficos(request):
    sincronizar_fixas(request.user)
    hoje = date.today()
    mes_atual = date(hoje.year, hoje.month, 1)
    periodo = request.GET.get('periodo', '6m')

    n_proj = 3  # meses futuros projetados
    if periodo == '3m':
        inicio = _mes_atras(hoje, 2)
    elif periodo == '6m':
        inicio = _mes_atras(hoje, 5)
    elif periodo == '1a':
        inicio = _mes_atras(hoje, 11)
    elif periodo == 'ano_atual':
        inicio = date(hoje.year, 1, 1)
    elif periodo == 'prox_3m':
        inicio = mes_atual
        n_proj = 3
    elif periodo == 'prox_6m':
        inicio = mes_atual
        n_proj = 6
    else:
        inicio = None

    qs = Transacao.objects.filter(usuario=request.user)
    if inicio:
        qs = qs.filter(data__gte=inicio)

    # ── Projeção em memória: restante do mês atual + n_proj meses futuros ──
    fim_proj = _data_parcela(mes_atual, n_proj + 1) - timedelta(days=1)  # último dia do n-ésimo mês futuro
    previstos = projetar_fixas(request.user, hoje + timedelta(days=1), fim_proj)

    prev_rec, prev_desp = {}, {}
    for p in previstos:
        m = date(p['data'].year, p['data'].month, 1)
        alvo = prev_rec if p['tipo'] == 'receita' else prev_desp
        alvo[m] = alvo.get(m, 0.0) + float(p['valor'])

    tem_realizado = qs.exists()
    tem_dados = tem_realizado or bool(previstos)

    if tem_dados:
        if inicio:
            # período selecionado define o início, mesmo sem dados (meses zerados)
            mes_ini = date(inicio.year, inicio.month, 1)
        elif tem_realizado:
            primeira = qs.order_by('data').values_list('data', flat=True).first()
            mes_ini = date(primeira.year, primeira.month, 1)
        else:
            mes_ini = mes_atual
        mes_fim = date(fim_proj.year, fim_proj.month, 1)

        meses = []
        m = mes_ini
        while m <= mes_fim:
            meses.append(m)
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)

        idx_atual = meses.index(mes_atual)

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
        rec_data  = [rec_mens.get(m, 0)  if m <= mes_atual else None for m in meses]
        desp_data = [desp_mens.get(m, 0) if m <= mes_atual else None for m in meses]

        # Previsto por mês: mês atual = realizado + restante; futuros = só projeção
        rec_prev_data, desp_prev_data = [], []
        for m in meses:
            if m < mes_atual:
                rec_prev_data.append(None)
                desp_prev_data.append(None)
            elif m == mes_atual:
                rec_prev_data.append(round(rec_mens.get(m, 0) + prev_rec.get(m, 0.0), 2))
                desp_prev_data.append(round(desp_mens.get(m, 0) + prev_desp.get(m, 0.0), 2))
            else:
                rec_prev_data.append(round(prev_rec.get(m, 0.0), 2))
                desp_prev_data.append(round(prev_desp.get(m, 0.0), 2))

        # Saldo realizado (até hoje) + extensão prevista
        saldo_data, saldo = [], 0
        for m in meses:
            if m <= mes_atual:
                saldo = round(saldo + rec_mens.get(m, 0) - desp_mens.get(m, 0), 2)
                saldo_data.append(saldo)
            else:
                saldo_data.append(None)

        saldo_prev_data = [None] * len(meses)
        saldo_p = saldo_data[idx_atual] or 0
        saldo_prev_data[idx_atual] = saldo_p  # ponto de conexão com a linha realizada
        saldo_p = round(saldo_p + prev_rec.get(mes_atual, 0.0) - prev_desp.get(mes_atual, 0.0), 2)
        for i in range(idx_atual + 1, len(meses)):
            m = meses[i]
            saldo_p = round(saldo_p + prev_rec.get(m, 0.0) - prev_desp.get(m, 0.0), 2)
            saldo_prev_data[i] = saldo_p

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
        rec_prev_data = desp_prev_data = saldo_prev_data = []
        cat_desp = cat_rec = {'labels': [], 'data': []}

    return render(request, 'financeiro/graficos.html', {
        'periodo':           periodo,
        'periodos':          PERIODOS,
        'labels':            json.dumps(labels),
        'rec_data':          json.dumps(rec_data),
        'desp_data':         json.dumps(desp_data),
        'saldo_data':        json.dumps(saldo_data),
        'rec_prev_data':     json.dumps(rec_prev_data),
        'desp_prev_data':    json.dumps(desp_prev_data),
        'saldo_prev_data':   json.dumps(saldo_prev_data),
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
    entidades, _ = _entidades_ctx(request.user)
    todas_cat = Categoria.objects.filter(usuario=request.user)
    form = TransacaoFixaForm(request.POST or None, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        tf = form.save(commit=False)
        tf.usuario = request.user
        tf.save()
        sincronizar_fixas(request.user)
        return redirect('fixas')
    return render(request, 'financeiro/transacao_fixa_form.html', {
        'form': form, 'todas_cat': todas_cat, 'entidades': entidades,
        'titulo': 'Nova recorrente',
    })


@login_required
def editar_fixa(request, pk):
    tf = get_object_or_404(TransacaoFixa, pk=pk, usuario=request.user)
    entidades, _ = _entidades_ctx(request.user)
    todas_cat = Categoria.objects.filter(usuario=request.user)
    form = TransacaoFixaForm(request.POST or None, instance=tf, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.ultima_geracao = date.today()   # novas ocorrências usam os valores editados
        obj.save()
        return redirect('fixas')
    return render(request, 'financeiro/transacao_fixa_form.html', {
        'form': form, 'todas_cat': todas_cat, 'entidades': entidades,
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


# ── EMPRÉSTIMOS ───────────────────────────────────────────────────────────────

@login_required
def emprestimos(request):
    hoje = date.today()
    qs = (Emprestimo.objects
          .filter(usuario=request.user)
          .prefetch_related('parcelas')
          .select_related('entidade'))
    items = []
    for emp in qs:
        parcelas = list(emp.parcelas.all())
        n_total = len(parcelas)
        n_pagas = sum(1 for p in parcelas if p.paga)
        valor_restante = sum(p.valor for p in parcelas if not p.paga)
        proxima = next((p for p in parcelas if not p.paga), None)
        progresso_pct = round(n_pagas / n_total * 100) if n_total else 0
        items.append({
            'obj': emp,
            'n_pagas': n_pagas,
            'n_total': n_total,
            'valor_restante': valor_restante,
            'proxima': proxima,
            'progresso_pct': progresso_pct,
        })
    return render(request, 'financeiro/emprestimos.html', {'items': items, 'hoje': hoje})


@login_required
def novo_emprestimo(request):
    entidades, _ = _entidades_ctx(request.user)
    com_juros = False
    form = EmprestimoForm(request.POST or None, usuario=request.user)
    if request.method == 'POST':
        com_juros = bool(request.POST.get('taxa_juros', '').strip())
        if form.is_valid():
            personalizado = request.POST.get('personalizado') == 'true'
            emp = form.save(commit=False)
            emp.usuario = request.user
            emp.save()
            if personalizado:
                datas = request.POST.getlist('parcela_data')
                valores = request.POST.getlist('parcela_valor')
                emp.criar_parcelas_personalizadas(datas, valores)
            else:
                emp.gerar_parcelas()
            return redirect('emprestimos')
    return render(request, 'financeiro/emprestimo_form.html', {
        'form': form, 'entidades': entidades,
        'titulo': 'Novo empréstimo', 'com_juros': com_juros,
    })


@login_required
def editar_emprestimo(request, pk):
    emp = get_object_or_404(Emprestimo, pk=pk, usuario=request.user)
    entidades, _ = _entidades_ctx(request.user)
    com_juros = emp.com_juros
    form = EmprestimoForm(request.POST or None, instance=emp, usuario=request.user)
    if request.method == 'POST':
        com_juros = bool(request.POST.get('taxa_juros', '').strip())
        if form.is_valid():
            personalizado = request.POST.get('personalizado') == 'true'
            campos_fin = ('valor_total', 'n_parcelas', 'taxa_juros', 'tipo_amortizacao', 'data_inicio')
            antes = {c: getattr(emp, c) for c in campos_fin}
            obj = form.save()
            if personalizado:
                datas = request.POST.getlist('parcela_data')
                valores = request.POST.getlist('parcela_valor')
                obj.parcelas.all().delete()
                obj.criar_parcelas_personalizadas(datas, valores)
            elif any(getattr(obj, c) != antes[c] for c in campos_fin):
                obj.parcelas.all().delete()
                obj.gerar_parcelas()
            return redirect('emprestimos')
    return render(request, 'financeiro/emprestimo_form.html', {
        'form': form, 'entidades': entidades,
        'titulo': 'Editar empréstimo', 'obj': emp, 'com_juros': com_juros,
    })


@login_required
def excluir_emprestimo(request, pk):
    emp = get_object_or_404(Emprestimo, pk=pk, usuario=request.user)
    if request.method == 'POST':
        emp.delete()
    return redirect('emprestimos')


@login_required
def toggle_parcela(request, pk):
    parcela = get_object_or_404(ParcelaEmprestimo, pk=pk, emprestimo__usuario=request.user)
    if request.method == 'POST':
        parcela.paga = not parcela.paga
        parcela.data_pagamento = date.today() if parcela.paga else None
        parcela.save(update_fields=['paga', 'data_pagamento'])
    return redirect('emprestimos')


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


@login_required
def metas(request):
    import calendar as _cal
    hoje = date.today()
    qs = Meta.objects.filter(usuario=request.user).select_related('categoria')

    n_ativas     = qs.filter(concluida=False).count()
    n_concluidas = qs.filter(concluida=True).count()

    proximas = [
        m for m in qs.filter(concluida=False, data_fim__isnull=False)
        if m.dias_restantes() is not None and 0 <= m.dias_restantes() <= 30
    ]
    proximas.sort(key=lambda m: m.data_fim)

    mm = hoje.month - 3
    yy = hoje.year
    while mm <= 0:
        mm += 12; yy -= 1
    inicio_3m = date(yy, mm, 1)

    cats_com_meta = set(
        qs.filter(concluida=False, tipo='limite_gasto', categoria__isnull=False)
        .values_list('categoria_id', flat=True)
    )
    top_cats = list(
        Transacao.objects
        .filter(usuario=request.user, tipo='despesa',
                data__gte=inicio_3m, categoria__isnull=False)
        .values('categoria_id', 'categoria__nome')
        .annotate(total=Sum('valor'))
        .order_by('-total')[:5]
    )
    sugestoes = []
    for cat in top_cats:
        if cat['categoria_id'] not in cats_com_meta:
            media = float(cat['total']) / 3
            sugestoes.append({
                'categoria_id':    cat['categoria_id'],
                'categoria_nome':  cat['categoria__nome'],
                'media_mensal':    round(media, 2),
                'limite_sugerido': round(media * 1.1, 2),
            })

    totais_eco = []
    for i in range(1, 4):
        m2 = hoje.month - i; y2 = hoje.year
        while m2 <= 0:
            m2 += 12; y2 -= 1
        ini = date(y2, m2, 1)
        fim = date(y2, m2, _cal.monthrange(y2, m2)[1])
        rec  = float(Transacao.objects.filter(usuario=request.user, tipo='receita',  data__gte=ini, data__lte=fim).aggregate(t=Sum('valor'))['t'] or 0)
        desp = float(Transacao.objects.filter(usuario=request.user, tipo='despesa', data__gte=ini, data__lte=fim).aggregate(t=Sum('valor'))['t'] or 0)
        totais_eco.append(rec - desp)
    economia_media = round(sum(totais_eco) / 3, 2)

    return render(request, 'financeiro/metas.html', {
        'metas': qs,
        'n_ativas': n_ativas,
        'n_concluidas': n_concluidas,
        'proximas': proximas,
        'sugestoes': sugestoes[:3],
        'economia_media': economia_media,
        'hoje': hoje,
    })


@login_required
def nova_meta(request):
    form = MetaForm(request.POST or None, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        m = form.save(commit=False)
        m.usuario = request.user
        m.save()
        return redirect('metas')
    return render(request, 'financeiro/meta_form.html', {
        'form': form, 'titulo': 'Nova meta', 'categorias': Categoria.objects.filter(usuario=request.user, tipo='despesa'),
    })


@login_required
def editar_meta(request, pk):
    meta = get_object_or_404(Meta, pk=pk, usuario=request.user)
    form = MetaForm(request.POST or None, instance=meta, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('metas')
    return render(request, 'financeiro/meta_form.html', {
        'form': form, 'titulo': 'Editar meta', 'meta': meta,
        'categorias': Categoria.objects.filter(usuario=request.user, tipo='despesa'),
    })


@login_required
def excluir_meta(request, pk):
    meta = get_object_or_404(Meta, pk=pk, usuario=request.user)
    if request.method == 'POST':
        meta.delete()
    return redirect('metas')


@login_required
def toggle_meta(request, pk):
    meta = get_object_or_404(Meta, pk=pk, usuario=request.user)
    if request.method == 'POST':
        meta.concluida = not meta.concluida
        meta.save(update_fields=['concluida'])
    return redirect('metas')


@login_required
def ajustar_meta(request, pk):
    meta = get_object_or_404(Meta, pk=pk, usuario=request.user)
    if request.method == 'POST':
        from decimal import Decimal
        val = request.POST.get('ajuste', '0').replace(',', '.')
        meta.ajuste = Decimal(val)
        meta.save(update_fields=['ajuste'])
    return redirect('metas')


def _proxima_data_pagamento(dia, dia_util=False):
    """Retorna a próxima data de pagamento a partir de hoje."""
    import calendar as _cal
    hoje = date.today()

    if not dia:
        return hoje

    if dia_util:
        from .models import _nth_business_day
        d = _nth_business_day(hoje.year, hoje.month, dia)
        if d and d >= hoje:
            return d
        m = hoje.month % 12 + 1
        y = hoje.year + (1 if hoje.month == 12 else 0)
        return _nth_business_day(y, m, dia) or hoje
    else:
        try:
            d = date(hoje.year, hoje.month, dia)
            if d >= hoje:
                return d
        except ValueError:
            pass
        m = hoje.month % 12 + 1
        y = hoje.year + (1 if hoje.month == 12 else 0)
        ultimo = _cal.monthrange(y, m)[1]
        return date(y, m, min(dia, ultimo))


def _ensure_catalogo():
    if not CategoriaEssencial.objects.exists():
        CategoriaEssencial.sincronizar_catalogo()


def _get_or_create_categoria_financeiro(usuario, nome, tipo):
    cat, _ = Categoria.objects.get_or_create(
        usuario=usuario, nome=nome, tipo=tipo,
    )
    return cat


def _criar_tf_essencial(usuario, cat, valor, dia, dia_util, obs, sufixo=''):
    """Cria a TransacaoFixa mensal vinculada a um essencial."""
    from decimal import Decimal as D
    cat_fin = _get_or_create_categoria_financeiro(usuario, cat.nome, cat.tipo)
    return TransacaoFixa.objects.create(
        usuario=usuario, tipo=cat.tipo,
        descricao=cat.nome + sufixo,
        valor=valor or D('0'), frequencia='mensal',
        data_inicio=_proxima_data_pagamento(dia, dia_util),
        categoria=cat_fin, observacao=obs, ativa=True,
    )


@login_required
def essenciais(request):
    _ensure_catalogo()
    catalogo = list(CategoriaEssencial.objects.all())
    ativas = {e.categoria_id: e for e in Essencial.objects.filter(usuario=request.user).select_related('categoria', 'transacao_fixa')}

    grupos = {}
    for cat in catalogo:
        key = (cat.tipo, cat.prioridade)
        grupos.setdefault(key, []).append({'cat': cat, 'essencial': ativas.get(cat.pk)})

    ORDEM_PRIORIDADE = {'fundamental': 0, 'importante': 1, 'opcional': 2}
    prev_tipo = None
    grupos_ordenados = []
    for (tipo, prioridade), itens in sorted(
        grupos.items(),
        key=lambda x: (x[0][0] != 'receita', ORDEM_PRIORIDADE.get(x[0][1], 9)),
    ):
        mostrar_cabecalho = tipo != prev_tipo
        grupos_ordenados.append({
            'tipo': tipo,
            'prioridade': prioridade,
            'itens': itens,
            'mostrar_cabecalho': mostrar_cabecalho,
        })
        prev_tipo = tipo

    return render(request, 'financeiro/essenciais.html', {
        'grupos': grupos_ordenados,
        'n_ativos': len(ativas),
        'hoje': date.today(),
    })


def _salvar_essencial_salario(request, ess, is_novo=False):
    """Lê os campos de salário do POST e atualiza/cria o Essencial."""
    from decimal import Decimal as D
    tipo_sal  = request.POST.get('tipo_salario', 'fixo')
    freq_pag  = request.POST.get('freq_pagamento', 'mensal')
    valor_str = request.POST.get('valor', '').replace(',', '.').strip()
    fixo_str  = request.POST.get('valor_fixo', '').replace(',', '.').strip()
    valor     = D(valor_str) if valor_str else None
    valor_fixo = D(fixo_str) if fixo_str else None

    ess.tipo_salario   = tipo_sal
    ess.freq_pagamento = freq_pag
    ess.valor_fixo     = valor_fixo
    # Para fixo: valor = fixo; para comissao: valor = None; fixo_comissao: valor = fixo (base)
    if tipo_sal == 'fixo':
        ess.valor = valor
    elif tipo_sal == 'fixo_comissao':
        ess.valor = valor_fixo
    else:
        ess.valor = None


@login_required
def ativar_essencial(request, slug):
    _ensure_catalogo()
    cat = get_object_or_404(CategoriaEssencial, slug=slug)
    if Essencial.objects.filter(usuario=request.user, categoria=cat).exists():
        return redirect('essenciais')

    if request.method == 'POST':
        from decimal import Decimal as D
        valor_str = request.POST.get('valor', '').replace(',', '.').strip()
        valor = D(valor_str) if valor_str else None
        dia = request.POST.get('dia_vencimento', '').strip()
        dia2 = request.POST.get('dia_vencimento_2', '').strip()
        dia_int  = int(dia)  if dia.isdigit()  and 1 <= int(dia)  <= 31 else None
        dia2_int = int(dia2) if dia2.isdigit() and 1 <= int(dia2) <= 31 else None
        dia_util   = request.POST.get('dia_util')   == '1'
        dia_util_2 = request.POST.get('dia_util_2') == '1'
        obs = request.POST.get('observacao', '').strip()

        data_inicio = _proxima_data_pagamento(dia_int, dia_util)

        ess = Essencial(
            usuario=request.user, categoria=cat,
            valor=valor, dia_vencimento=dia_int, dia_vencimento_2=dia2_int,
            dia_util=dia_util, dia_util_2=dia_util_2,
            data_inicio=data_inicio, observacao=obs,
        )

        # Lê valor_2 para quinzenal
        valor2_str = request.POST.get('valor_2', '').replace(',', '.').strip()
        valor_2 = D(valor2_str) if valor2_str else None
        ess.valor_2 = valor_2

        def _criar_tf(val, di, du, descricao_extra=''):
            return _criar_tf_essencial(request.user, cat, val, di, du, obs, descricao_extra)

        tf = tf2 = None
        is_quinzenal = ess.freq_pagamento == 'quinzenal'

        if cat.slug == 'salario':
            _salvar_essencial_salario(request, ess)
            # fixo: valor integral; fixo_comissao: só a parte fixa (comissão é manual)
            if ess.tipo_salario in ('fixo', 'fixo_comissao'):
                tf = _criar_tf(ess.valor, dia_int, dia_util,
                               ' (1ª parcela)' if is_quinzenal else '')
                if is_quinzenal and dia2_int:
                    tf2 = _criar_tf(valor_2 or ess.valor, dia2_int, dia_util_2, ' (2ª parcela)')
        else:
            tf = _criar_tf(valor, dia_int, False,
                           ' (1ª parcela)' if is_quinzenal else '')
            if is_quinzenal and dia2_int:
                tf2 = _criar_tf(valor_2 or valor, dia2_int, False, ' (2ª parcela)')

        ess.transacao_fixa = tf
        ess.transacao_fixa_2 = tf2
        ess.save()
        return redirect('essenciais')

    return render(request, 'financeiro/essencial_form.html', {
        'cat': cat, 'acao': 'ativar', 'hoje': date.today(),
        'sal_choices': Essencial.TIPO_SALARIO_CHOICES,
    })


@login_required
def editar_essencial(request, slug):
    cat = get_object_or_404(CategoriaEssencial, slug=slug)
    ess = get_object_or_404(Essencial, usuario=request.user, categoria=cat)

    if request.method == 'POST':
        from decimal import Decimal as D
        obs  = request.POST.get('observacao', '').strip()
        dia  = request.POST.get('dia_vencimento', '').strip()
        dia2 = request.POST.get('dia_vencimento_2', '').strip()
        ess.dia_vencimento   = int(dia)  if dia.isdigit()  and 1 <= int(dia)  <= 31 else None
        ess.dia_vencimento_2 = int(dia2) if dia2.isdigit() and 1 <= int(dia2) <= 31 else None
        ess.dia_util         = request.POST.get('dia_util')   == '1'
        ess.dia_util_2       = request.POST.get('dia_util_2') == '1'
        ess.observacao       = obs

        valor2_str = request.POST.get('valor_2', '').replace(',', '.').strip()
        ess.valor_2 = D(valor2_str) if valor2_str else None

        if cat.slug == 'salario':
            _salvar_essencial_salario(request, ess)
            # fixo e fixo_comissao têm parte previsível → recorrente ativa
            tem_fixa = ess.tipo_salario in ('fixo', 'fixo_comissao')
            is_quinzenal = ess.freq_pagamento == 'quinzenal'
            if ess.transacao_fixa_id:
                TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
                    valor=ess.valor or D('0'), ativa=tem_fixa, observacao=obs,
                )
            elif tem_fixa:
                ess.transacao_fixa = _criar_tf_essencial(
                    request.user, cat, ess.valor, ess.dia_vencimento, ess.dia_util, obs,
                    ' (1ª parcela)' if is_quinzenal else '',
                )
            if ess.transacao_fixa_2_id:
                TransacaoFixa.objects.filter(pk=ess.transacao_fixa_2_id).update(
                    valor=ess.valor_2 or ess.valor or D('0'), ativa=tem_fixa, observacao=obs,
                )
            elif tem_fixa and is_quinzenal and ess.dia_vencimento_2:
                ess.transacao_fixa_2 = _criar_tf_essencial(
                    request.user, cat, ess.valor_2 or ess.valor,
                    ess.dia_vencimento_2, ess.dia_util_2, obs, ' (2ª parcela)',
                )
        else:
            valor_str = request.POST.get('valor', '').replace(',', '.').strip()
            ess.valor = D(valor_str) if valor_str else None
            if ess.transacao_fixa_id:
                TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
                    valor=ess.valor or D('0'), observacao=obs,
                )
            if ess.transacao_fixa_2_id:
                TransacaoFixa.objects.filter(pk=ess.transacao_fixa_2_id).update(
                    valor=ess.valor_2 or ess.valor or D('0'), observacao=obs,
                )

        ess.save()
        return redirect('essenciais')

    return render(request, 'financeiro/essencial_form.html', {
        'cat': cat, 'ess': ess, 'acao': 'editar', 'hoje': date.today(),
        'sal_choices': Essencial.TIPO_SALARIO_CHOICES,
    })


@login_required
def registrar_salario(request):
    """Registra o recebimento do salário (comissão ou fixo+comissão) via modal."""
    try:
        ess = Essencial.objects.get(usuario=request.user, categoria__slug='salario', ativa=True)
    except Essencial.DoesNotExist:
        return redirect('painel')

    if request.method == 'POST':
        from decimal import Decimal as D
        comissao_str = request.POST.get('comissao', '0').replace(',', '.').strip()
        fixo_str     = request.POST.get('valor_fixo', '0').replace(',', '.').strip()
        comissao = D(comissao_str) if comissao_str else D('0')
        fixo     = D(fixo_str)     if fixo_str     else D('0')

        # Se a parte fixa já é gerada pela recorrente, registra só a comissão
        fixa_automatica = bool(
            ess.tipo_salario == 'fixo_comissao' and ess.transacao_fixa_id
            and TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id, ativa=True).exists()
        )
        if fixa_automatica:
            fixo = D('0')
        total = fixo + comissao

        if total > 0:
            cat_fin = _get_or_create_categoria_financeiro(request.user, 'Salário', 'receita')
            descricao = 'Salário'
            if comissao > 0:
                descricao = 'Salário + Comissão' if fixo > 0 else 'Comissão'
            Transacao.objects.create(
                usuario=request.user, tipo='receita',
                descricao=descricao, valor=total,
                data=date.today(), categoria=cat_fin,
            )
        ess.ultimo_registro = date.today()
        ess.save(update_fields=['ultimo_registro'])

    return redirect('painel')


@login_required
def desativar_essencial(request, slug):
    cat = get_object_or_404(CategoriaEssencial, slug=slug)
    ess = get_object_or_404(Essencial, usuario=request.user, categoria=cat)
    if request.method == 'POST':
        ids = [i for i in [ess.transacao_fixa_id, ess.transacao_fixa_2_id] if i]
        if ids:
            TransacaoFixa.objects.filter(pk__in=ids).update(ativa=False)
        ess.delete()
    return redirect('essenciais')


# ── IMPORTAÇÃO DE EXTRATO ─────────────────────────────────────────────────────

def _marcar_duplicatas(usuario, lancamentos):
    """Anota cada lançamento com 'duplicata' e o motivo, comparando com o já existente."""
    if not lancamentos:
        return lancamentos

    datas = [l['data'] for l in lancamentos]
    existentes = list(
        Transacao.objects.filter(usuario=usuario, data__gte=min(datas), data__lte=max(datas))
        .values('fitid', 'tipo', 'valor', 'data', 'descricao')
    )
    fitids = {e['fitid'] for e in existentes if e['fitid']}
    chaves = {(e['tipo'], e['data'], e['valor']) for e in existentes}

    for l in lancamentos:
        motivo = ''
        if l['fitid'] and l['fitid'] in fitids:
            motivo = 'Já importado anteriormente'
        elif (l['tipo'], l['data'], l['valor']) in chaves:
            motivo = 'Já existe lançamento igual nesta data'
        l['duplicata'] = bool(motivo)
        l['motivo_duplicata'] = motivo
    return lancamentos


def _aplicar_regras(usuario, lancamentos):
    """Sugere categoria (e entidade) para cada lançamento com base nas regras ativas."""
    regras = list(
        RegraCategoria.objects.filter(usuario=usuario, ativa=True)
        .select_related('categoria', 'entidade')
    )
    for l in lancamentos:
        l['categoria_id'] = None
        l['categoria_nome'] = ''
        l['entidade_id'] = None
        for r in regras:
            if r.combina(l['descricao'], l['tipo']):
                l['categoria_id'] = r.categoria_id
                l['categoria_nome'] = r.categoria.nome
                l['entidade_id'] = r.entidade_id
                break
    return lancamentos


def _serializar(lancamentos):
    return [{
        **l,
        'data': l['data'].isoformat(),
        'valor': str(l['valor']),
    } for l in lancamentos]


def _desserializar(dados):
    from datetime import datetime as _dt
    return [{
        **d,
        'data': _dt.strptime(d['data'], '%Y-%m-%d').date(),
        'valor': Decimal(d['valor']),
    } for d in dados]


@login_required
def importar_extrato(request):
    """Passo 1: upload do arquivo (OFX ou CSV)."""
    erro = None

    if request.method == 'POST' and request.FILES.get('arquivo'):
        arquivo = request.FILES['arquivo']
        nome = arquivo.name
        conteudo = arquivo.read()
        ext = nome.rsplit('.', 1)[-1].lower() if '.' in nome else ''

        try:
            if ext in ('ofx', 'ofc', 'qfx'):
                lancamentos, meta = parse_ofx(conteudo)
                lancamentos = _aplicar_regras(request.user, _marcar_duplicatas(request.user, lancamentos))
                request.session['import_extrato'] = {
                    'arquivo_nome': nome, 'formato': 'ofx', 'meta': {
                        'banco': meta['banco'], 'conta': meta['conta'],
                        'periodo_inicio': meta['periodo_inicio'].isoformat() if meta['periodo_inicio'] else None,
                        'periodo_fim': meta['periodo_fim'].isoformat() if meta['periodo_fim'] else None,
                    },
                    'lancamentos': _serializar(lancamentos),
                }
                return redirect('revisar_extrato')

            elif ext in ('csv', 'txt', 'tsv'):
                cabecalho, linhas = ler_csv(conteudo)
                request.session['import_csv'] = {
                    'arquivo_nome': nome,
                    'cabecalho': cabecalho,
                    'linhas': linhas[:2000],
                    'sugestao': detectar_colunas(cabecalho),
                }
                return redirect('mapear_csv')

            elif ext == 'pdf':
                erro = ('PDFs são lidos direto no navegador — ative o JavaScript e '
                        'selecione o arquivo novamente.')

            else:
                erro = 'Formato não suportado. Envie um arquivo .ofx, .csv ou .pdf.'

        except ExtratoInvalido as e:
            erro = str(e)
        except Exception:
            erro = 'Não foi possível ler o arquivo. Verifique se ele não está corrompido.'

    return render(request, 'financeiro/importar_extrato.html', {
        'erro': erro,
        'importacoes': ImportacaoExtrato.objects.filter(usuario=request.user)[:5],
    })


@login_required
def importar_pdf(request):
    """Recebe as linhas de texto extraídas do PDF pelo navegador (pdf.js/OCR)."""
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'erro': 'Método inválido.'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        linhas = payload.get('linhas') or []
        nome = (payload.get('arquivo_nome') or 'extrato.pdf')[:255]
    except (ValueError, AttributeError):
        return JsonResponse({'ok': False, 'erro': 'Dados inválidos.'}, status=400)

    if not isinstance(linhas, list) or not linhas:
        return JsonResponse({'ok': False, 'erro': 'Nenhum texto foi extraído do PDF.'}, status=400)

    try:
        lancamentos = parse_linhas_caixa([str(l) for l in linhas][:5000])
    except ExtratoInvalido as e:
        return JsonResponse({'ok': False, 'erro': str(e)}, status=400)

    conf = conferencia_lancamentos(lancamentos)
    lancamentos = _aplicar_regras(request.user, _marcar_duplicatas(request.user, lancamentos))
    request.session['import_extrato'] = {
        'arquivo_nome': nome, 'formato': 'pdf',
        'meta': meta_do_extrato([str(l) for l in linhas]),
        'conferencia': conf,
        'lancamentos': _serializar(lancamentos),
    }
    return JsonResponse({'ok': True, 'n': len(lancamentos), 'redirect': '/importar/revisar/'})


@login_required
def mapear_csv(request):
    """Passo 1.5 (só CSV): escolher quais colunas são data, valor, descrição e tipo."""
    dados = request.session.get('import_csv')
    if not dados:
        return redirect('importar_extrato')

    erro = None
    if request.method == 'POST':
        def _idx(campo, obrigatorio=False):
            v = request.POST.get(campo, '')
            if v.isdigit():
                return int(v)
            return None

        col_data = _idx('col_data')
        col_valor = _idx('col_valor')
        col_desc = _idx('col_desc')
        col_tipo = _idx('col_tipo')

        if col_data is None or col_valor is None:
            erro = 'Escolha ao menos as colunas de data e valor.'
        else:
            try:
                lancamentos = parse_csv(dados['linhas'], col_data, col_valor, col_desc, col_tipo)
                lancamentos = _aplicar_regras(request.user, _marcar_duplicatas(request.user, lancamentos))
                request.session['import_extrato'] = {
                    'arquivo_nome': dados['arquivo_nome'], 'formato': 'csv',
                    'meta': {'banco': '', 'conta': '', 'periodo_inicio': None, 'periodo_fim': None},
                    'lancamentos': _serializar(lancamentos),
                }
                del request.session['import_csv']
                return redirect('revisar_extrato')
            except ExtratoInvalido as e:
                erro = str(e)

    return render(request, 'financeiro/mapear_csv.html', {
        'cabecalho': dados['cabecalho'],
        'previa': dados['linhas'][:5],
        'sugestao': dados['sugestao'],
        'arquivo_nome': dados['arquivo_nome'],
        'erro': erro,
    })


@login_required
def revisar_extrato(request):
    """Passo 2: revisar, ajustar categorias e confirmar a importação."""
    dados = request.session.get('import_extrato')
    if not dados:
        return redirect('importar_extrato')

    lancamentos = _desserializar(dados['lancamentos'])

    if request.method == 'POST':
        selecionados = set(request.POST.getlist('incluir'))
        imp = ImportacaoExtrato.objects.create(
            usuario=request.user,
            arquivo_nome=dados['arquivo_nome'],
            formato=dados['formato'],
            banco=dados['meta'].get('banco') or '',
            conta=dados['meta'].get('conta') or '',
            periodo_inicio=lancamentos[0]['data'] if lancamentos else None,
            periodo_fim=lancamentos[-1]['data'] if lancamentos else None,
        )

        novas = []
        for i, l in enumerate(lancamentos):
            if str(i) not in selecionados:
                continue
            cat_id = request.POST.get(f'categoria_{i}') or None
            novas.append(Transacao(
                usuario=request.user, tipo=l['tipo'],
                descricao=l['descricao'], valor=l['valor'], data=l['data'],
                categoria_id=int(cat_id) if cat_id and cat_id.isdigit() else None,
                entidade_id=l.get('entidade_id'),
                fitid=l.get('fitid', ''), importacao=imp,
                observacao=f'Importado de {dados["arquivo_nome"]}',
            ))

        if novas:
            Transacao.objects.bulk_create(novas)
        imp.n_importadas = len(novas)
        imp.n_ignoradas = len(lancamentos) - len(novas)
        imp.save(update_fields=['n_importadas', 'n_ignoradas'])

        del request.session['import_extrato']
        messages.success(
            request,
            f'{len(novas)} lançamento(s) importado(s) de {dados["arquivo_nome"]}.'
            + (f' {imp.n_ignoradas} ignorado(s).' if imp.n_ignoradas else '')
        )
        return redirect('importar_extrato')

    itens = []
    for i, l in enumerate(lancamentos):
        itens.append({**l, 'idx': i})

    total_rec = sum(l['valor'] for l in lancamentos if l['tipo'] == 'receita')
    total_desp = sum(l['valor'] for l in lancamentos if l['tipo'] == 'despesa')
    n_dup = sum(1 for l in lancamentos if l['duplicata'])
    n_susp = sum(1 for l in lancamentos if l.get('suspeito'))

    conf = dados.get('conferencia')

    meta = dict(dados['meta'])
    meta['periodo_inicio'] = lancamentos[0]['data'] if lancamentos else None
    meta['periodo_fim'] = lancamentos[-1]['data'] if lancamentos else None

    return render(request, 'financeiro/revisar_extrato.html', {
        'itens': itens,
        'arquivo_nome': dados['arquivo_nome'],
        'formato': dados['formato'],
        'conferencia': conf,
        'meta': meta,
        'total_receitas': total_rec,
        'total_despesas': total_desp,
        'n_total': len(lancamentos),
        'n_duplicatas': n_dup,
        'n_suspeitos': n_susp,
        'n_novos': len(lancamentos) - n_dup,
        'cats_receita': Categoria.objects.filter(usuario=request.user, tipo='receita'),
        'cats_despesa': Categoria.objects.filter(usuario=request.user, tipo='despesa'),
    })


@login_required
def cancelar_importacao(request):
    request.session.pop('import_extrato', None)
    request.session.pop('import_csv', None)
    return redirect('importar_extrato')


# ── REGRAS DE CATEGORIZAÇÃO ───────────────────────────────────────────────────

@login_required
def regras(request):
    return render(request, 'financeiro/regras.html', {
        'regras': RegraCategoria.objects.filter(usuario=request.user).select_related('categoria', 'entidade'),
    })


@login_required
def nova_regra(request):
    form = RegraCategoriaForm(request.POST or None, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        r = form.save(commit=False)
        r.usuario = request.user
        r.save()
        return redirect('regras')
    return render(request, 'financeiro/regra_form.html', {
        'form': form, 'titulo': 'Nova regra',
        'categorias': Categoria.objects.filter(usuario=request.user),
    })


@login_required
def editar_regra(request, pk):
    regra = get_object_or_404(RegraCategoria, pk=pk, usuario=request.user)
    form = RegraCategoriaForm(request.POST or None, instance=regra, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('regras')
    return render(request, 'financeiro/regra_form.html', {
        'form': form, 'titulo': 'Editar regra', 'obj': regra,
        'categorias': Categoria.objects.filter(usuario=request.user),
    })


@login_required
def excluir_regra(request, pk):
    regra = get_object_or_404(RegraCategoria, pk=pk, usuario=request.user)
    if request.method == 'POST':
        regra.delete()
    return redirect('regras')


@login_required
def toggle_regra(request, pk):
    regra = get_object_or_404(RegraCategoria, pk=pk, usuario=request.user)
    if request.method == 'POST':
        regra.ativa = not regra.ativa
        regra.save(update_fields=['ativa'])
    return redirect('regras')


# ── HISTÓRICO DE VIDA ─────────────────────────────────────────────────────────

def _marcos_automaticos(usuario):
    """Marcos derivados dos dados financeiros — calculados, nunca gravados."""
    marcos = []

    primeira = (Transacao.objects.filter(usuario=usuario)
                .order_by('data', 'criado_em').first())
    if primeira:
        marcos.append({
            'data': primeira.data, 'icone': '🌱', 'tipo_label': 'Início',
            'titulo': 'Primeiro registro no Helpy',
            'descricao': f'{primeira.nome_display} — sua jornada financeira começou aqui.',
            'valor': primeira.valor, 'auto': True,
        })

    maior_rec = Transacao.objects.filter(usuario=usuario, tipo='receita').order_by('-valor').first()
    if maior_rec:
        marcos.append({
            'data': maior_rec.data, 'icone': '📈', 'tipo_label': 'Recorde',
            'titulo': 'Maior receita registrada',
            'descricao': maior_rec.nome_display,
            'valor': maior_rec.valor, 'auto': True,
        })

    maior_desp = Transacao.objects.filter(usuario=usuario, tipo='despesa').order_by('-valor').first()
    if maior_desp:
        marcos.append({
            'data': maior_desp.data, 'icone': '💸', 'tipo_label': 'Recorde',
            'titulo': 'Maior despesa registrada',
            'descricao': maior_desp.nome_display,
            'valor': maior_desp.valor, 'auto': True,
        })

    for meta in Meta.objects.filter(usuario=usuario, concluida=True):
        marcos.append({
            'data': meta.data_fim or meta.data_inicio, 'icone': '🎯', 'tipo_label': 'Meta',
            'titulo': f'Meta concluída: {meta.nome}',
            'descricao': meta.get_tipo_display(),
            'valor': meta.valor_alvo, 'auto': True,
        })

    for emp in Emprestimo.objects.filter(usuario=usuario).prefetch_related('parcelas'):
        parcelas = list(emp.parcelas.all())
        if parcelas and all(p.paga for p in parcelas):
            datas = [p.data_pagamento or p.data_vencimento for p in parcelas]
            marcos.append({
                'data': max(datas), 'icone': '🔓', 'tipo_label': 'Empréstimo',
                'titulo': f'Empréstimo quitado: {emp.nome_display}',
                'descricao': f'{len(parcelas)} parcela{"s" if len(parcelas) > 1 else ""} — {emp.get_tipo_display().lower()}',
                'valor': emp.valor_total, 'auto': True,
            })

    for ess in (Essencial.objects.filter(usuario=usuario)
                .select_related('categoria').order_by('criado_em')[:1]):
        marcos.append({
            'data': ess.data_inicio, 'icone': '⚙️', 'tipo_label': 'Organização',
            'titulo': 'Primeiro essencial configurado',
            'descricao': ess.categoria.nome,
            'valor': ess.valor, 'auto': True,
        })

    return marcos


def _estatisticas_vida(usuario):
    qs = Transacao.objects.filter(usuario=usuario)
    total_rec = qs.filter(tipo='receita').aggregate(t=Sum('valor'))['t'] or 0
    total_desp = qs.filter(tipo='despesa').aggregate(t=Sum('valor'))['t'] or 0

    primeira = qs.order_by('data').values_list('data', flat=True).first()
    meses = 0
    if primeira:
        hoje = date.today()
        meses = (hoje.year - primeira.year) * 12 + (hoje.month - primeira.month) + 1

    return {
        'total_receitas': total_rec,
        'total_despesas': total_desp,
        'saldo_total': total_rec - total_desp,
        'n_transacoes': qs.count(),
        'meses_ativos': meses,
        'media_receita_mes': (total_rec / meses) if meses else 0,
        'media_despesa_mes': (total_desp / meses) if meses else 0,
        'desde': primeira,
    }


def _patrimonio_anual(usuario):
    """Saldo acumulado ao fim de cada ano com movimento."""
    rows = (Transacao.objects.filter(usuario=usuario)
            .values('data__year', 'tipo')
            .annotate(t=Sum('valor')).order_by('data__year'))
    por_ano = {}
    for r in rows:
        ano = r['data__year']
        d = por_ano.setdefault(ano, {'receita': 0.0, 'despesa': 0.0})
        d[r['tipo']] = float(r['t'])

    labels, acumulado, saldo = [], [], 0.0
    for ano in sorted(por_ano):
        saldo = round(saldo + por_ano[ano]['receita'] - por_ano[ano]['despesa'], 2)
        labels.append(str(ano))
        acumulado.append(saldo)
    return labels, acumulado


@login_required
def historico_vida(request):
    sincronizar_fixas(request.user)

    tipo_filtro = request.GET.get('tipo', '')
    ano_filtro = request.GET.get('ano', '')

    eventos = [{
        'data': e.data, 'icone': e.icone, 'tipo_label': e.get_tipo_display(),
        'titulo': e.titulo, 'descricao': e.descricao, 'valor': e.valor_efetivo,
        'auto': False, 'destaque': e.destaque, 'pk': e.pk, 'tipo': e.tipo,
        'transacao': e.transacao,
    } for e in EventoVida.objects.filter(usuario=request.user).select_related('transacao')]

    itens = eventos + _marcos_automaticos(request.user)

    anos = sorted({i['data'].year for i in itens}, reverse=True)

    if tipo_filtro == 'manual':
        itens = [i for i in itens if not i['auto']]
    elif tipo_filtro == 'auto':
        itens = [i for i in itens if i['auto']]
    elif tipo_filtro:
        itens = [i for i in itens if i.get('tipo') == tipo_filtro]

    if ano_filtro.isdigit():
        itens = [i for i in itens if i['data'].year == int(ano_filtro)]

    itens.sort(key=lambda i: i['data'], reverse=True)

    # Agrupa por ano para a linha do tempo
    grupos = []
    for item in itens:
        if not grupos or grupos[-1]['ano'] != item['data'].year:
            grupos.append({'ano': item['data'].year, 'itens': []})
        grupos[-1]['itens'].append(item)

    pat_labels, pat_data = _patrimonio_anual(request.user)

    return render(request, 'financeiro/historico_vida.html', {
        'grupos': grupos,
        'n_itens': len(itens),
        'stats': _estatisticas_vida(request.user),
        'anos': anos,
        'ano_filtro': ano_filtro,
        'tipo_filtro': tipo_filtro,
        'tipos': EventoVida.TIPO_CHOICES,
        'pat_labels': json.dumps(pat_labels),
        'pat_data': json.dumps(pat_data),
        'tem_patrimonio': len(pat_labels) > 0,
        'simbolo': request.user.simbolo_moeda,
    })


def _salvar_evento_vida(request, form):
    """Salva o marco e resolve o vínculo com transação (nenhum/existente/nova)."""
    ev = form.save(commit=False)
    ev.usuario = request.user

    if form.cleaned_data.get('vinculo') == 'nova':
        t = Transacao.objects.create(
            usuario=request.user,
            tipo=form.cleaned_data.get('nova_tipo') or 'despesa',
            descricao=ev.titulo,
            valor=ev.valor,
            data=ev.data,
            categoria=form.cleaned_data.get('nova_categoria'),
            observacao=ev.descricao,
        )
        ev.transacao = t

    ev.save()
    return ev


@login_required
def novo_evento_vida(request):
    form = EventoVidaForm(request.POST or None, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        _salvar_evento_vida(request, form)
        return redirect('historico_vida')
    return render(request, 'financeiro/evento_vida_form.html', {
        'form': form, 'titulo': 'Novo marco',
        'categorias': Categoria.objects.filter(usuario=request.user),
    })


@login_required
def editar_evento_vida(request, pk):
    ev = get_object_or_404(EventoVida, pk=pk, usuario=request.user)
    form = EventoVidaForm(request.POST or None, instance=ev, usuario=request.user)
    if request.method == 'POST' and form.is_valid():
        _salvar_evento_vida(request, form)
        return redirect('historico_vida')
    return render(request, 'financeiro/evento_vida_form.html', {
        'form': form, 'titulo': 'Editar marco', 'obj': ev,
        'categorias': Categoria.objects.filter(usuario=request.user),
    })


@login_required
def excluir_evento_vida(request, pk):
    ev = get_object_or_404(EventoVida, pk=pk, usuario=request.user)
    if request.method == 'POST':
        ev.delete()
    return redirect('historico_vida')


@login_required
def criar_saldo_extra(request):
    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        valor_str = request.POST.get('valor', '0').replace(',', '.')
        tipo = request.POST.get('tipo', 'outro')
        if nome:
            from decimal import Decimal
            SaldoExtra.objects.create(
                usuario=request.user, nome=nome,
                valor=Decimal(valor_str), tipo=tipo,
            )
    return redirect('painel')


@login_required
def atualizar_saldo_extra(request, pk):
    se = get_object_or_404(SaldoExtra, pk=pk, usuario=request.user)
    if request.method == 'POST':
        from decimal import Decimal
        valor_str = request.POST.get('valor', '0').replace(',', '.')
        se.valor = Decimal(valor_str)
        se.save(update_fields=['valor', 'atualizado_em'])
    return redirect('painel')


@login_required
def excluir_saldo_extra(request, pk):
    se = get_object_or_404(SaldoExtra, pk=pk, usuario=request.user)
    if request.method == 'POST':
        se.delete()
    return redirect('painel')
