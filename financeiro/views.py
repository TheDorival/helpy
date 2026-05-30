import csv
import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CategoriaForm, EmprestimoForm, EntidadeForm, MetaForm, TransacaoFixaForm, TransacaoForm
from .models import (Categoria, CategoriaEssencial, Emprestimo, Entidade, Essencial,
                     Meta, ParcelaEmprestimo, SaldoExtra, Transacao, TransacaoFixa, _avancar_data)

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
    sincronizar_fixas(request.user, limite=min(ctx['fim'], date.today()))
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
    sincronizar_fixas(request.user, limite=min(ctx['fim'], date.today()))
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

        tf = None
        if cat.slug == 'salario':
            _salvar_essencial_salario(request, ess)
            # Só cria recorrente automática para salário fixo
            if ess.tipo_salario == 'fixo':
                cat_fin = _get_or_create_categoria_financeiro(request.user, cat.nome, cat.tipo)
                tf = TransacaoFixa.objects.create(
                    usuario=request.user, tipo=cat.tipo, descricao=cat.nome,
                    valor=ess.valor or D('0'), frequencia=cat.frequencia,
                    data_inicio=data_inicio, categoria=cat_fin, observacao=obs, ativa=True,
                )
        else:
            cat_fin = _get_or_create_categoria_financeiro(request.user, cat.nome, cat.tipo)
            tf = TransacaoFixa.objects.create(
                usuario=request.user, tipo=cat.tipo, descricao=cat.nome,
                valor=valor or D('0'), frequencia=cat.frequencia,
                data_inicio=data_inicio, categoria=cat_fin, observacao=obs, ativa=True,
            )

        ess.transacao_fixa = tf
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

        if cat.slug == 'salario':
            _salvar_essencial_salario(request, ess)
            if ess.transacao_fixa_id:
                # Só mantém recorrente ativa se for fixo
                TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
                    valor=ess.valor or D('0'),
                    ativa=(ess.tipo_salario == 'fixo'),
                    observacao=obs,
                )
        else:
            valor_str = request.POST.get('valor', '').replace(',', '.').strip()
            ess.valor = D(valor_str) if valor_str else None
            if ess.transacao_fixa_id:
                TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
                    valor=ess.valor or D('0'), observacao=obs,
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
        total = fixo + comissao

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
        if ess.transacao_fixa_id:
            TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(ativa=False)
        ess.delete()
    return redirect('essenciais')


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
