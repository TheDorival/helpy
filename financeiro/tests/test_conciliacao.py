"""Conciliação entre lançamentos importados e ocorrências de recorrentes."""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import (Categoria, CategoriaEssencial, Essencial, RegraCategoria,
                               Transacao, TransacaoFixa)
from financeiro.views import _conciliar_com_recorrentes, _preparar_lancamentos, sincronizar_fixas

Usuario = get_user_model()


def lancamento(data, valor, tipo='receita', descricao='RECEBIMENTO TED SALARIO Fulano'):
    return {
        'data': data, 'valor': Decimal(valor), 'tipo': tipo,
        'descricao': descricao, 'texto_completo': descricao,
        'fitid': '', 'suspeito': False, 'validado': False,
        'motivo_suspeita': '', 'operacao': '',
    }


class ConciliacaoTests(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='conc', password='x')
        self.hoje = date.today()

    def _recorrente(self, **kwargs):
        padrao = dict(
            usuario=self.u, tipo='receita', descricao='Salário',
            valor=Decimal('2000'), frequencia='mensal', ativa=True,
        )
        padrao.update(kwargs)
        return TransacaoFixa.objects.create(**padrao)

    def test_casa_com_ocorrencia_ja_gerada(self):
        """Banco pagou dois dias antes: atualiza em vez de duplicar."""
        prevista = self.hoje - timedelta(days=2)
        self._recorrente(data_inicio=prevista)
        sincronizar_fixas(self.u)

        real = prevista - timedelta(days=2)
        itens = _conciliar_com_recorrentes(self.u, [lancamento(real, '2000')])
        self.assertIsNotNone(itens[0].get('conciliar_id'))
        self.assertEqual(itens[0]['conciliar_data'], prevista)

    def test_casa_com_ocorrencia_ainda_pendente(self):
        """Importação feita antes da data prevista marca a recorrente."""
        prevista = self.hoje + timedelta(days=4)
        tf = self._recorrente(data_inicio=prevista)

        itens = _conciliar_com_recorrentes(self.u, [lancamento(self.hoje + timedelta(days=1), '2000')])
        self.assertEqual(itens[0].get('antecipa_fixa_id'), tf.pk)
        self.assertEqual(itens[0]['antecipa_ate'], prevista)

    def test_diferenca_de_valor_dentro_da_margem(self):
        prevista = self.hoje - timedelta(days=1)
        self._recorrente(data_inicio=prevista)
        sincronizar_fixas(self.u)
        itens = _conciliar_com_recorrentes(self.u, [lancamento(prevista, '2180')])   # +9%
        self.assertIsNotNone(itens[0].get('conciliar_id'))

    def test_diferenca_de_valor_grande_nao_concilia(self):
        prevista = self.hoje - timedelta(days=1)
        self._recorrente(data_inicio=prevista)
        sincronizar_fixas(self.u)
        itens = _conciliar_com_recorrentes(self.u, [lancamento(prevista, '3500')])   # +75%
        self.assertIsNone(itens[0].get('conciliar_id'))

    def test_fora_da_janela_de_dias_nao_concilia(self):
        prevista = self.hoje - timedelta(days=20)
        self._recorrente(data_inicio=prevista)
        sincronizar_fixas(self.u)
        itens = _conciliar_com_recorrentes(self.u, [lancamento(self.hoje, '2000')])
        self.assertIsNone(itens[0].get('conciliar_id'))

    def test_transacao_avulsa_nao_e_candidata(self):
        """Só ocorrências geradas por recorrentes entram na conciliação."""
        Transacao.objects.create(
            usuario=self.u, tipo='despesa', descricao='Compra avulsa',
            valor=Decimal('50'), data=self.hoje - timedelta(days=1),
        )
        itens = _conciliar_com_recorrentes(
            self.u, [lancamento(self.hoje, '50', tipo='despesa', descricao='COMPRA Loja')],
        )
        self.assertIsNone(itens[0].get('conciliar_id'))

    def test_tipos_diferentes_nao_casam(self):
        prevista = self.hoje - timedelta(days=1)
        self._recorrente(data_inicio=prevista)
        sincronizar_fixas(self.u)
        itens = _conciliar_com_recorrentes(
            self.u, [lancamento(prevista, '2000', tipo='despesa')],
        )
        self.assertIsNone(itens[0].get('conciliar_id'))

    def test_uma_ocorrencia_nao_atende_dois_lancamentos(self):
        prevista = self.hoje - timedelta(days=1)
        self._recorrente(data_inicio=prevista)
        sincronizar_fixas(self.u)
        itens = _conciliar_com_recorrentes(
            self.u, [lancamento(prevista, '2000'), lancamento(prevista, '2000')],
        )
        conciliados = [i for i in itens if i.get('conciliar_id')]
        self.assertEqual(len(conciliados), 1)


class RegraComRecorrenteTests(TestCase):
    """A regra aponta a recorrente e amplia a tolerância."""

    def setUp(self):
        self.u = Usuario.objects.create_user(username='regra', password='x')
        self.hoje = date.today()
        self.tf = TransacaoFixa.objects.create(
            usuario=self.u, tipo='receita', descricao='Salário',
            valor=Decimal('2000'), frequencia='mensal', ativa=True,
            data_inicio=self.hoje + timedelta(days=12),
        )

    def test_sem_regra_valor_muito_diferente_nao_casa(self):
        itens = _preparar_lancamentos(self.u, [lancamento(self.hoje + timedelta(days=1), '3500')])
        self.assertIsNone(itens[0].get('antecipa_fixa_id'))

    def test_com_regra_casa_mesmo_com_valor_diferente(self):
        RegraCategoria.objects.create(
            usuario=self.u, termo='RECEBIMENTO TED SALARIO',
            recorrente=self.tf, aplica_a='receita',
        )
        itens = _preparar_lancamentos(self.u, [lancamento(self.hoje + timedelta(days=1), '3500')])
        self.assertEqual(itens[0].get('antecipa_fixa_id'), self.tf.pk)

    def test_regra_diferencia_operacao(self):
        """Mesmo nome, operações distintas: só o salário casa."""
        RegraCategoria.objects.create(
            usuario=self.u, termo='RECEBIMENTO TED SALARIO',
            recorrente=self.tf, aplica_a='receita',
        )
        itens = _preparar_lancamentos(self.u, [
            lancamento(self.hoje + timedelta(days=1), '2000',
                       descricao='RECEBIMENTO TED SALARIO Leonardo'),
            lancamento(self.hoje + timedelta(days=2), '2000',
                       descricao='PIX RECEBIDO Leonardo'),
        ])
        self.assertEqual(itens[0].get('antecipa_fixa_id'), self.tf.pk)
        self.assertIsNone(itens[1].get('antecipa_fixa_id'))


class SalarioQuinzenalTests(TestCase):
    """Duas parcelas com texto idêntico: cada uma deve achar a sua."""

    def setUp(self):
        self.u = Usuario.objects.create_user(username='quinzenal', password='x')
        self.hoje = date.today()
        cat_ess, _ = CategoriaEssencial.objects.get_or_create(
            slug='salario', defaults=dict(nome='Salário', tipo='receita', icone='💰'),
        )
        base = self.hoje - timedelta(days=30)
        self.p1 = TransacaoFixa.objects.create(
            usuario=self.u, tipo='receita', descricao='Salário (1ª parcela)',
            valor=Decimal('620'), frequencia='mensal', ativa=True, data_inicio=base,
        )
        self.p2 = TransacaoFixa.objects.create(
            usuario=self.u, tipo='receita', descricao='Salário (2ª parcela)',
            valor=Decimal('1421'), frequencia='mensal', ativa=True,
            data_inicio=base + timedelta(days=10),
        )
        Essencial.objects.create(
            usuario=self.u, categoria=cat_ess, data_inicio=base,
            transacao_fixa=self.p1, transacao_fixa_2=self.p2,
            tipo_salario='fixo', freq_pagamento='quinzenal',
        )
        sincronizar_fixas(self.u)
        RegraCategoria.objects.create(
            usuario=self.u, termo='RECEBIMENTO TED SALARIO',
            recorrente=self.p1, aplica_a='receita',      # aponta só a 1ª
        )

    def test_cada_parcela_casa_com_a_sua(self):
        d1 = self.hoje - timedelta(days=30)
        d2 = d1 + timedelta(days=10)
        itens = _preparar_lancamentos(self.u, [
            lancamento(d1, '620'),
            lancamento(d2, '1421'),
        ])
        conciliados = {
            Transacao.objects.get(pk=i['conciliar_id']).origem_fixa_id: i['valor']
            for i in itens if i.get('conciliar_id')
        }
        self.assertEqual(conciliados.get(self.p1.pk), Decimal('620'))
        self.assertEqual(conciliados.get(self.p2.pk), Decimal('1421'))

    def test_ordem_invertida_nao_troca_as_parcelas(self):
        d1 = self.hoje - timedelta(days=30)
        d2 = d1 + timedelta(days=10)
        itens = _preparar_lancamentos(self.u, [
            lancamento(d2, '1421'),
            lancamento(d1, '620'),
        ])
        for i in itens:
            origem = Transacao.objects.get(pk=i['conciliar_id']).origem_fixa_id
            esperado = self.p1.pk if i['valor'] == Decimal('620') else self.p2.pk
            self.assertEqual(origem, esperado)


class ImportacaoCompletaTests(TestCase):
    """Fluxo de ponta a ponta pela view, como no navegador."""

    def setUp(self):
        self.u = Usuario.objects.create_user(username='fluxo', password='x')
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)
        self.hoje = date.today()

    def _importar(self, linhas):
        self.c.post('/importar/pdf/',
                    data=json.dumps({'arquivo_nome': 'extrato.pdf', 'linhas': linhas}),
                    content_type='application/json')
        return self.c.get('/importar/revisar/')

    def test_conciliacao_atualiza_em_vez_de_duplicar(self):
        prevista = self.hoje - timedelta(days=2)
        TransacaoFixa.objects.create(
            usuario=self.u, tipo='receita', descricao='Salário',
            valor=Decimal('2000'), frequencia='mensal', ativa=True, data_inicio=prevista,
        )
        sincronizar_fixas(self.u)
        real = prevista - timedelta(days=1)

        self._importar([
            f'{real:%d/%m/%Y} - 07:00:00 070000 RECEBIMENTO TED SALARIO Empresa 2.000,00 C 5.000,00 C'
        ])
        self.c.post('/importar/revisar/', {'incluir': ['0']})

        transacoes = Transacao.objects.filter(usuario=self.u)
        self.assertEqual(transacoes.count(), 1)
        self.assertEqual(transacoes.first().data, real)

    def test_duplicata_vem_desmarcada(self):
        Transacao.objects.create(
            usuario=self.u, tipo='despesa', descricao='Loja',
            valor=Decimal('50'), data=date(2026, 7, 10),
        )
        resposta = self._importar([
            '10/07/2026 - 10:00:00 101000 COMPRA CARTAO DEBITO Loja 50,00 D 100,00 C'
        ])
        self.assertContains(resposta, 'Já existe lançamento igual')

    def test_edicao_manual_na_revisao(self):
        self._importar([
            '10/07/2026 - 10:00:00 101000 COMPRA CARTAO DEBITO Loja 50,00 D 100,00 C'
        ])
        self.c.post('/importar/revisar/', {
            'incluir': ['0'], 'valor_0': '75.50',
            'descricao_0': 'Mercado corrigido', 'tipo_0': 'despesa', 'data_0': '2026-07-11',
        })
        t = Transacao.objects.get(usuario=self.u)
        self.assertEqual(t.valor, Decimal('75.50'))
        self.assertEqual(t.descricao, 'Mercado corrigido')
        self.assertEqual(t.data, date(2026, 7, 11))

    def test_regra_aplica_categoria_na_importacao(self):
        cat = Categoria.objects.create(usuario=self.u, nome='Delivery', tipo='despesa')
        RegraCategoria.objects.create(usuario=self.u, termo='IFOOD',
                                      categoria=cat, aplica_a='despesa')
        self._importar([
            '10/07/2026 - 10:00:00 101000 COMPRA CARTAO DEBITO Ifood.com Agencia 50,00 D 100,00 C'
        ])
        self.c.post('/importar/revisar/', {'incluir': ['0'], 'categoria_0': str(cat.pk)})
        self.assertEqual(Transacao.objects.get(usuario=self.u).categoria_id, cat.pk)

    def test_lancamento_nao_selecionado_nao_entra(self):
        self._importar([
            '10/07/2026 - 10:00:00 101000 COMPRA CARTAO DEBITO Loja 50,00 D 100,00 C'
        ])
        self.c.post('/importar/revisar/', {'incluir': []})
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 0)

    def test_extrato_ilegivel_retorna_erro(self):
        resposta = self.c.post(
            '/importar/pdf/',
            data=json.dumps({'arquivo_nome': 'x.pdf', 'linhas': ['nada aqui']}),
            content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertFalse(resposta.json()['ok'])
