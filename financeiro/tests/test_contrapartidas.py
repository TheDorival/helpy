"""Contrapartidas: uma transação que gera outra, de sinal oposto, no futuro.

Caso que motivou: Pix no crédito entra como receita hoje e volta como despesa
na fatura do mês seguinte, com taxa e às vezes parcelado.
"""

import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import (Categoria, Contrapartida, ParcelaContrapartida,
                               RegraCategoria, Transacao, _proxima_fatura)
from financeiro.views import (_gerar_contrapartida, _regra_para_transacao,
                              projetar_contrapartidas, projetar_fixas)

Usuario = get_user_model()


class BaseContrapartida(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.cat_rec = Categoria.objects.create(usuario=self.u, nome='Pix crédito', tipo='receita')
        self.cat_desp = Categoria.objects.create(usuario=self.u, nome='Fatura', tipo='despesa')

    def regra(self, **kwargs):
        padrao = dict(
            usuario=self.u, termo='PIX CREDITO', categoria=self.cat_rec,
            aplica_a='receita', gera_contrapartida=True,
            contrapartida_taxa=Decimal('0'), contrapartida_parcelas=1,
            contrapartida_categoria=self.cat_desp,
        )
        padrao.update(kwargs)
        return RegraCategoria.objects.create(**padrao)

    def transacao(self, valor='1000', data=date(2026, 3, 23), tipo='receita'):
        return Transacao.objects.create(
            usuario=self.u, tipo=tipo, valor=Decimal(valor), data=data,
            descricao='PIX CREDITO Acme',
        )


class DataDaFaturaTests(TestCase):
    """A cobrança cai no vencimento seguinte, nunca no mesmo dia da compra."""

    def test_dia_da_fatura_ainda_por_vir_no_mes(self):
        self.assertEqual(_proxima_fatura(date(2026, 3, 5), 10), date(2026, 3, 10))

    def test_dia_da_fatura_ja_passou_vai_para_o_mes_seguinte(self):
        self.assertEqual(_proxima_fatura(date(2026, 3, 23), 10), date(2026, 4, 10))

    def test_compra_no_proprio_dia_do_vencimento_vai_para_o_seguinte(self):
        """Comprou no dia 10 com fatura no dia 10: só cai na próxima."""
        self.assertEqual(_proxima_fatura(date(2026, 3, 10), 10), date(2026, 4, 10))

    def test_dia_31_em_mes_curto(self):
        self.assertEqual(_proxima_fatura(date(2026, 1, 31), 31), date(2026, 2, 28))

    def test_virada_de_ano(self):
        self.assertEqual(_proxima_fatura(date(2026, 12, 20), 5), date(2027, 1, 5))


class GeracaoTests(BaseContrapartida):

    def test_sinal_invertido(self):
        cp = _gerar_contrapartida(self.transacao(), self.regra())
        self.assertEqual(cp.tipo, 'despesa')

    def test_despesa_gera_receita(self):
        t = self.transacao(tipo='despesa')
        cp = _gerar_contrapartida(t, self.regra(aplica_a='despesa'))
        self.assertEqual(cp.tipo, 'receita')

    def test_taxa_aplicada(self):
        cp = _gerar_contrapartida(self.transacao(), self.regra(contrapartida_taxa=Decimal('6.5')))
        self.assertEqual(cp.valor_total, Decimal('1065.00'))

    def test_sem_taxa_espelha_o_valor(self):
        cp = _gerar_contrapartida(self.transacao(), self.regra())
        self.assertEqual(cp.valor_total, Decimal('1000.00'))

    def test_regra_sem_contrapartida_nao_gera(self):
        self.assertIsNone(
            _gerar_contrapartida(self.transacao(), self.regra(gera_contrapartida=False))
        )

    def test_sem_regra_nao_gera(self):
        self.assertIsNone(_gerar_contrapartida(self.transacao(), None))

    def test_categoria_da_cobranca_e_a_da_regra(self):
        cp = _gerar_contrapartida(self.transacao(), self.regra())
        self.assertEqual(cp.categoria, self.cat_desp)

    def test_herda_o_bolso_da_origem(self):
        t = self.transacao()
        t.conta = 'dinheiro'
        t.save(update_fields=['conta'])
        self.assertEqual(_gerar_contrapartida(t, self.regra()).conta, 'dinheiro')

    def test_nao_cria_transacao_futura(self):
        """A dívida é certa, mas ainda não aconteceu — não vira lançamento."""
        _gerar_contrapartida(self.transacao(), self.regra(contrapartida_parcelas=3))
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 1)


class ParcelamentoTests(BaseContrapartida):

    def test_parcela_unica(self):
        cp = _gerar_contrapartida(self.transacao(), self.regra(contrapartida_dia=10))
        parcelas = list(cp.parcelas.all())
        self.assertEqual(len(parcelas), 1)
        self.assertEqual(parcelas[0].data_vencimento, date(2026, 4, 10))

    def test_tres_parcelas_mensais(self):
        cp = _gerar_contrapartida(
            self.transacao(), self.regra(contrapartida_parcelas=3, contrapartida_dia=10),
        )
        datas = [p.data_vencimento for p in cp.parcelas.all()]
        self.assertEqual(datas, [date(2026, 4, 10), date(2026, 5, 10), date(2026, 6, 10)])

    def test_soma_das_parcelas_fecha_com_o_total(self):
        """Divisão que não fecha: 1000 em 3x. A sobra vai na última."""
        cp = _gerar_contrapartida(self.transacao(), self.regra(contrapartida_parcelas=3))
        valores = [p.valor for p in cp.parcelas.all()]
        self.assertEqual(sum(valores), cp.valor_total)
        self.assertEqual(valores[0], Decimal('333.33'))
        self.assertEqual(valores[-1], Decimal('333.34'))

    def test_soma_fecha_tambem_com_taxa(self):
        cp = _gerar_contrapartida(
            self.transacao(), self.regra(contrapartida_taxa=Decimal('6.5'),
                                         contrapartida_parcelas=7),
        )
        self.assertEqual(sum(p.valor for p in cp.parcelas.all()), Decimal('1065.00'))

    def test_sem_dia_usa_o_dia_da_transacao_no_mes_seguinte(self):
        cp = _gerar_contrapartida(self.transacao(data=date(2026, 3, 23)), self.regra())
        self.assertEqual(cp.parcelas.first().data_vencimento, date(2026, 4, 23))

    def test_numeracao_sequencial(self):
        cp = _gerar_contrapartida(self.transacao(), self.regra(contrapartida_parcelas=4))
        self.assertEqual([p.numero for p in cp.parcelas.all()], [1, 2, 3, 4])


class ProjecaoTests(BaseContrapartida):

    def setUp(self):
        super().setUp()
        self.cp = _gerar_contrapartida(
            self.transacao(), self.regra(contrapartida_parcelas=3, contrapartida_dia=10),
        )

    def test_parcelas_entram_na_projecao(self):
        itens = projetar_contrapartidas(self.u, date(2026, 4, 1), date(2026, 6, 30))
        self.assertEqual(len(itens), 3)
        self.assertTrue(all(i['tipo'] == 'despesa' for i in itens))

    def test_projecao_respeita_o_periodo(self):
        itens = projetar_contrapartidas(self.u, date(2026, 4, 1), date(2026, 4, 30))
        self.assertEqual(len(itens), 1)

    def test_projecao_filtra_por_tipo(self):
        self.assertEqual(len(projetar_contrapartidas(self.u, date(2026, 1, 1),
                                                     date(2026, 12, 31), tipo='receita')), 0)

    def test_parcela_quitada_sai_da_projecao(self):
        p = self.cp.parcelas.first()
        p.quitada = True
        p.save(update_fields=['quitada'])
        self.assertEqual(len(projetar_contrapartidas(self.u, date(2026, 1, 1), date(2026, 12, 31))), 2)

    def test_projetar_fixas_inclui_as_cobrancas(self):
        itens = projetar_fixas(self.u, date(2026, 4, 1), date(2026, 6, 30))
        self.assertEqual(len([i for i in itens if i.get('parcela')]), 3)

    def test_rotulo_mostra_a_parcela(self):
        itens = projetar_contrapartidas(self.u, date(2026, 4, 1), date(2026, 4, 30))
        self.assertIn('(1/3)', itens[0]['nome_display'])

    def test_nao_vaza_entre_usuarios(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        self.assertEqual(len(projetar_contrapartidas(outro, date(2026, 1, 1), date(2026, 12, 31))), 0)


class LancamentoManualTests(BaseContrapartida):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_regra_casa_com_lancamento_manual(self):
        self.regra()
        t = self.transacao()
        self.assertIsNotNone(_regra_para_transacao(self.u, t))

    def test_regra_de_outro_tipo_nao_casa(self):
        self.regra(aplica_a='despesa')
        self.assertIsNone(_regra_para_transacao(self.u, self.transacao()))

    def test_regra_inativa_nao_casa(self):
        self.regra(ativa=False)
        self.assertIsNone(_regra_para_transacao(self.u, self.transacao()))

    def test_receita_manual_gera_a_cobranca(self):
        self.regra(contrapartida_taxa=Decimal('5'), contrapartida_parcelas=2,
                   contrapartida_dia=10)
        self.c.post('/receitas/nova/', {
            'descricao': 'PIX CREDITO Acme', 'valor': '1000', 'data': '2026-03-23',
            'conta': 'banco',
        })
        cp = Contrapartida.objects.get(usuario=self.u)
        self.assertEqual(cp.valor_total, Decimal('1050.00'))
        self.assertEqual(cp.parcelas.count(), 2)

    def test_lancamento_sem_regra_nao_gera_nada(self):
        self.c.post('/receitas/nova/', {
            'descricao': 'Salário', 'valor': '1000', 'data': '2026-03-23', 'conta': 'banco',
        })
        self.assertEqual(Contrapartida.objects.count(), 0)


class ImportacaoTests(BaseContrapartida):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_importacao_gera_a_cobranca(self):
        RegraCategoria.objects.create(
            usuario=self.u, termo='CREDITO JUROS', categoria=self.cat_rec,
            aplica_a='receita', gera_contrapartida=True,
            contrapartida_taxa=Decimal('10'), contrapartida_parcelas=2,
            contrapartida_dia=10, contrapartida_categoria=self.cat_desp,
        )
        linhas = [
            '01/08/2026 - 03:04:10 000000 CREDITO JUROS 100,00 C 812,12 C',
            '01/08/2026 - 12:21:57 011221 COMPRA CARTAO DEBITO Unicompra 2,59 D 809,53 C',
        ]
        self.c.post('/importar/pdf/',
                    data=json.dumps({'arquivo_nome': 'e.pdf', 'linhas': linhas}),
                    content_type='application/json')
        self.c.get('/importar/revisar/')
        self.c.post('/importar/revisar/', {
            'incluir': ['0'],
            'data_0': '2026-08-01', 'descricao_0': 'CREDITO JUROS',
            'tipo_0': 'receita', 'valor_0': '100.00',
        })

        cp = Contrapartida.objects.get(usuario=self.u)
        self.assertEqual(cp.valor_total, Decimal('110.00'))
        self.assertEqual(cp.parcelas.count(), 2)
        self.assertEqual(cp.origem.descricao, 'CREDITO JUROS')

    def test_importacao_sem_regra_nao_gera(self):
        linhas = ['01/08/2026 - 03:04:10 000000 CREDITO JUROS 100,00 C 812,12 C']
        self.c.post('/importar/pdf/',
                    data=json.dumps({'arquivo_nome': 'e.pdf', 'linhas': linhas}),
                    content_type='application/json')
        self.c.get('/importar/revisar/')
        self.c.post('/importar/revisar/', {
            'incluir': ['0'], 'data_0': '2026-08-01', 'descricao_0': 'CREDITO JUROS',
            'tipo_0': 'receita', 'valor_0': '100.00',
        })
        self.assertEqual(Contrapartida.objects.count(), 0)


class QuitacaoTests(BaseContrapartida):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)
        self.cp = _gerar_contrapartida(
            self.transacao(), self.regra(contrapartida_parcelas=2, contrapartida_dia=10),
        )

    def test_confirmar_cria_a_transacao(self):
        p = self.cp.parcelas.first()
        self.c.post(f'/cobrancas/parcela/{p.pk}/quitar/', {'data': '2026-04-12'})

        p.refresh_from_db()
        self.assertTrue(p.quitada)
        self.assertIsNotNone(p.transacao)
        self.assertEqual(p.transacao.tipo, 'despesa')
        self.assertEqual(p.transacao.valor, p.valor)
        self.assertEqual(p.transacao.data, date(2026, 4, 12))

    def test_sem_data_usa_o_vencimento(self):
        p = self.cp.parcelas.first()
        self.c.post(f'/cobrancas/parcela/{p.pk}/quitar/')
        p.refresh_from_db()
        self.assertEqual(p.transacao.data, date(2026, 4, 10))

    def test_confirmar_duas_vezes_nao_duplica(self):
        p = self.cp.parcelas.first()
        self.c.post(f'/cobrancas/parcela/{p.pk}/quitar/')
        self.c.post(f'/cobrancas/parcela/{p.pk}/quitar/')
        self.assertEqual(Transacao.objects.filter(usuario=self.u, tipo='despesa').count(), 1)

    def test_get_nao_quita(self):
        p = self.cp.parcelas.first()
        self.c.get(f'/cobrancas/parcela/{p.pk}/quitar/')
        p.refresh_from_db()
        self.assertFalse(p.quitada)

    def test_nao_quita_parcela_alheia(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        c2 = Client(SERVER_NAME='localhost')
        c2.force_login(outro)
        p = self.cp.parcelas.first()
        resposta = c2.post(f'/cobrancas/parcela/{p.pk}/quitar/')
        self.assertEqual(resposta.status_code, 404)
        p.refresh_from_db()
        self.assertFalse(p.quitada)

    def test_excluir_remove_as_parcelas(self):
        self.c.post(f'/cobrancas/{self.cp.pk}/excluir/')
        self.assertEqual(Contrapartida.objects.count(), 0)
        self.assertEqual(ParcelaContrapartida.objects.count(), 0)

    def test_pagina_lista_as_cobrancas(self):
        pagina = self.c.get('/cobrancas/').content.decode()
        self.assertIn('PIX CREDITO Acme', pagina)
        self.assertIn('10/04/2026', pagina)

    def test_excluir_a_origem_leva_a_cobranca_junto(self):
        """Sem a transação de origem, a dívida não tem razão de existir."""
        self.cp.origem.delete()
        self.assertEqual(Contrapartida.objects.count(), 0)
