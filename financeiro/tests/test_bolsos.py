"""Bolsos: dinheiro, vale e conta bancária somam separado.

Sem isso uma gratificação em espécie infla o saldo bancário e a conferência
contra o extrato — que é o que prova que a importação está íntegra — quebra.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import (CONTA_CHOICES, AjusteSaldo, Categoria, SaldoExtra,
                               Transacao, TransacaoFixa, conta_e_restrita)
from helpy.views import _saldo_historico, _saldos_por_bolso

Usuario = get_user_model()


class BaseBolso(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.cat = Categoria.objects.create(usuario=self.u, nome='Geral', tipo='despesa')

    def lancar(self, tipo, valor, data, conta='banco'):
        return Transacao.objects.create(
            usuario=self.u, tipo=tipo, valor=Decimal(valor), data=data,
            conta=conta, descricao='mov',
        )


class SaldoPorBolsoTests(BaseBolso):

    def test_padrao_e_banco(self):
        t = Transacao.objects.create(usuario=self.u, tipo='despesa', valor=Decimal('10'),
                                     data=date(2026, 3, 1), descricao='x')
        self.assertEqual(t.conta, 'banco')

    def test_dinheiro_nao_entra_no_saldo_bancario(self):
        """O caso real: gratificação em espécie não move a conta."""
        self.lancar('receita', '1000', date(2026, 3, 1), 'banco')
        self.lancar('receita', '200', date(2026, 3, 2), 'dinheiro')
        self.assertEqual(_saldo_historico(self.u, 'banco'), Decimal('1000'))
        self.assertEqual(_saldo_historico(self.u, 'dinheiro'), Decimal('200'))

    def test_gasto_de_vale_nao_derruba_a_conta(self):
        self.lancar('receita', '1000', date(2026, 3, 1), 'banco')
        self.lancar('despesa', '35', date(2026, 3, 2), 'vale')
        self.assertEqual(_saldo_historico(self.u, 'banco'), Decimal('1000'))
        self.assertEqual(_saldo_historico(self.u, 'vale'), Decimal('-35'))

    def test_ancora_de_um_bolso_nao_afeta_outro(self):
        self.lancar('receita', '500', date(2026, 3, 1), 'dinheiro')
        AjusteSaldo.objects.create(usuario=self.u, conta='banco',
                                   data=date(2026, 4, 1), valor=Decimal('9999'))
        self.assertEqual(_saldo_historico(self.u, 'banco'), Decimal('9999'))
        self.assertEqual(_saldo_historico(self.u, 'dinheiro'), Decimal('500'))

    def test_ancora_de_dinheiro_conta_carteira(self):
        """Contar a carteira e informar o valor: mesma mecânica do extrato."""
        self.lancar('receita', '100', date(2026, 3, 1), 'dinheiro')
        AjusteSaldo.objects.create(usuario=self.u, conta='dinheiro',
                                   data=date(2026, 3, 10), valor=Decimal('80'))
        self.lancar('despesa', '30', date(2026, 3, 15), 'dinheiro')
        self.assertEqual(_saldo_historico(self.u, 'dinheiro'), Decimal('50'))

    def test_vigentes_traz_uma_ancora_por_bolso(self):
        AjusteSaldo.objects.create(usuario=self.u, conta='banco',
                                   data=date(2026, 1, 1), valor=Decimal('1'))
        AjusteSaldo.objects.create(usuario=self.u, conta='banco',
                                   data=date(2026, 5, 1), valor=Decimal('2'))
        AjusteSaldo.objects.create(usuario=self.u, conta='dinheiro',
                                   data=date(2026, 2, 1), valor=Decimal('3'))
        vigentes = AjusteSaldo.vigentes(self.u)
        self.assertEqual(set(vigentes), {'banco', 'dinheiro'})
        self.assertEqual(vigentes['banco'].valor, Decimal('2'))
        self.assertEqual(vigentes['dinheiro'].valor, Decimal('3'))

    def test_bolsos_lista_so_o_que_existe(self):
        """Quem nunca usou dinheiro não precisa ver uma linha zerada."""
        self.lancar('receita', '10', date(2026, 3, 1), 'banco')
        contas = [b['conta'] for b in _saldos_por_bolso(self.u)]
        self.assertEqual(contas, ['banco'])

    def test_bolsos_aparecem_quando_usados(self):
        self.lancar('receita', '10', date(2026, 3, 1), 'dinheiro')
        self.lancar('despesa', '5', date(2026, 3, 2), 'vale')
        contas = [b['conta'] for b in _saldos_por_bolso(self.u)]
        self.assertEqual(contas, ['banco', 'dinheiro', 'vale'])

    def test_bolso_aparece_so_pela_ancora(self):
        AjusteSaldo.objects.create(usuario=self.u, conta='dinheiro',
                                   data=date(2026, 3, 1), valor=Decimal('50'))
        contas = [b['conta'] for b in _saldos_por_bolso(self.u)]
        self.assertIn('dinheiro', contas)

    def test_ordem_segue_conta_choices(self):
        for valor, _ in CONTA_CHOICES:
            self.lancar('receita', '1', date(2026, 3, 1), valor)
        contas = [b['conta'] for b in _saldos_por_bolso(self.u)]
        self.assertEqual(contas, [v for v, _ in CONTA_CHOICES])

    def test_apenas_o_vale_e_restrito(self):
        self.assertTrue(conta_e_restrita('vale'))
        for conta in ('banco', 'dinheiro', 'outro'):
            self.assertFalse(conta_e_restrita(conta))

    def test_bolso_nao_vaza_entre_usuarios(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        Transacao.objects.create(usuario=outro, tipo='receita', valor=Decimal('500'),
                                 data=date(2026, 3, 1), conta='dinheiro', descricao='x')
        self.assertEqual(_saldo_historico(self.u, 'dinheiro'), Decimal('0'))


class MovimentoIndiferenteAoBolsoTests(BaseBolso):
    """Quanto entrou e quanto saiu não depende do bolso — só o saldo depende."""

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_despesa_em_dinheiro_conta_no_resumo(self):
        self.lancar('despesa', '40', date.today(), 'dinheiro')
        pagina = self.c.get('/resumo/').content.decode()
        self.assertIn('40,00', pagina)

    def test_despesa_em_dinheiro_nao_muda_o_saldo_bancario(self):
        self.lancar('despesa', '40', date.today(), 'dinheiro')
        self.assertEqual(_saldo_historico(self.u, 'banco'), Decimal('0'))


class PainelBolsosTests(BaseBolso):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_vale_fica_fora_do_disponivel(self):
        self.lancar('receita', '1000', date(2026, 3, 1), 'banco')
        self.lancar('receita', '300', date(2026, 3, 1), 'vale')
        resposta = self.c.get('/painel/')
        self.assertEqual(resposta.context['saldo_disponivel'], 1000.0)
        self.assertEqual(resposta.context['saldo_restrito'], 300.0)
        self.assertEqual(resposta.context['saldo_total'], 1300.0)

    def test_dinheiro_entra_no_disponivel(self):
        self.lancar('receita', '1000', date(2026, 3, 1), 'banco')
        self.lancar('receita', '150', date(2026, 3, 1), 'dinheiro')
        self.assertEqual(self.c.get('/painel/').context['saldo_disponivel'], 1150.0)

    def test_saldo_extra_de_vale_e_restrito(self):
        SaldoExtra.objects.create(usuario=self.u, nome='VR', valor=Decimal('400'), tipo='vale')
        SaldoExtra.objects.create(usuario=self.u, nome='Cripto', valor=Decimal('100'), tipo='cripto')
        resposta = self.c.get('/painel/')
        self.assertEqual(resposta.context['saldo_restrito'], 400.0)
        self.assertEqual(resposta.context['saldo_disponivel'], 100.0)

    def test_painel_mostra_os_bolsos_usados(self):
        self.lancar('receita', '250', date(2026, 3, 1), 'dinheiro')
        pagina = self.c.get('/painel/').content.decode()
        self.assertIn('Dinheiro', pagina)
        self.assertIn('250,00', pagina)


class AjustePorBolsoTests(BaseBolso):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_ajusta_o_bolso_escolhido(self):
        self.c.post('/saldo/ajustar/', {'conta': 'dinheiro', 'data': '2026-03-01',
                                        'valor': '200'})
        self.assertEqual(AjusteSaldo.vigente(self.u, 'dinheiro').valor, Decimal('200'))
        self.assertIsNone(AjusteSaldo.vigente(self.u, 'banco'))

    def test_bolso_invalido_cai_no_banco(self):
        self.c.post('/saldo/ajustar/', {'conta': 'inventado', 'data': '2026-03-01',
                                        'valor': '200'})
        self.assertEqual(AjusteSaldo.vigente(self.u, 'banco').valor, Decimal('200'))

    def test_sem_bolso_assume_banco(self):
        self.c.post('/saldo/ajustar/', {'data': '2026-03-01', 'valor': '200'})
        self.assertEqual(AjusteSaldo.vigente(self.u, 'banco').valor, Decimal('200'))

    def test_desfazer_atinge_so_o_bolso_pedido(self):
        AjusteSaldo.objects.create(usuario=self.u, conta='banco',
                                   data=date(2026, 3, 1), valor=Decimal('100'))
        AjusteSaldo.objects.create(usuario=self.u, conta='dinheiro',
                                   data=date(2026, 3, 1), valor=Decimal('50'))
        self.c.post('/saldo/ajustar/desfazer/', {'conta': 'dinheiro'})
        self.assertIsNone(AjusteSaldo.vigente(self.u, 'dinheiro'))
        self.assertIsNotNone(AjusteSaldo.vigente(self.u, 'banco'))


class OrigemDosLancamentosTests(BaseBolso):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_recorrente_repassa_o_bolso(self):
        tf = TransacaoFixa.objects.create(
            usuario=self.u, tipo='despesa', descricao='Almoço', valor=Decimal('30'),
            frequencia='mensal', data_inicio=date(2026, 1, 5), conta='vale',
        )
        from financeiro.views import sincronizar_fixas
        sincronizar_fixas(self.u, limite=date(2026, 3, 31))
        ocorrencias = Transacao.objects.filter(usuario=self.u, origem_fixa=tf)
        self.assertTrue(ocorrencias.exists())
        self.assertTrue(all(t.conta == 'vale' for t in ocorrencias))

    def test_lancamento_manual_aceita_o_bolso(self):
        self.c.post('/receitas/nova/', {
            'descricao': 'Gratificação', 'valor': '150', 'data': '2026-03-01',
            'conta': 'dinheiro',
        })
        t = Transacao.objects.filter(usuario=self.u).first()
        self.assertIsNotNone(t)
        self.assertEqual(t.conta, 'dinheiro')

    def test_importacao_e_sempre_banco(self):
        """Veio de extrato bancário — não há o que perguntar."""
        linhas = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 570,00 D 1.014,11 C',
        ]
        import json
        self.c.post('/importar/pdf/',
                    data=json.dumps({'arquivo_nome': 'e.pdf', 'linhas': linhas}),
                    content_type='application/json')
        self.c.get('/importar/revisar/')
        self.c.post('/importar/revisar/', {
            'incluir': ['0', '1'],
            'data_0': '2026-07-31', 'descricao_0': 'Debora', 'tipo_0': 'despesa', 'valor_0': '202.00',
            'data_1': '2026-07-31', 'descricao_1': 'Seul', 'tipo_1': 'despesa', 'valor_1': '570.00',
        })
        importadas = Transacao.objects.filter(usuario=self.u)
        self.assertTrue(importadas.exists())
        self.assertTrue(all(t.conta == 'banco' for t in importadas))
