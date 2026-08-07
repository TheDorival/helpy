"""Âncora de saldo: o painel parte do saldo real informado, não da soma de tudo."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import AjusteSaldo, Categoria, Transacao
from helpy.views import _saldo_historico

Usuario = get_user_model()


class BaseAjuste(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.cat = Categoria.objects.create(usuario=self.u, nome='Geral', tipo='despesa')

    def lancar(self, tipo, valor, data):
        return Transacao.objects.create(
            usuario=self.u, tipo=tipo, valor=Decimal(valor), data=data,
            descricao='mov', categoria=self.cat if tipo == 'despesa' else None,
        )


class SaldoHistoricoTests(BaseAjuste):

    def test_sem_ancora_soma_tudo(self):
        self.lancar('receita', '1000', date(2026, 1, 10))
        self.lancar('despesa', '250', date(2026, 2, 5))
        self.assertEqual(_saldo_historico(self.u), Decimal('750'))

    def test_ancora_substitui_o_passado(self):
        """Lançamentos anteriores à âncora já estão embutidos nela."""
        self.lancar('receita', '1000', date(2026, 1, 10))
        self.lancar('despesa', '250', date(2026, 2, 5))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 3, 1),
                                   valor=Decimal('4321.00'))
        self.assertEqual(_saldo_historico(self.u), Decimal('4321.00'))

    def test_movimentos_posteriores_entram(self):
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 3, 1),
                                   valor=Decimal('1000.00'))
        self.lancar('receita', '500', date(2026, 3, 2))
        self.lancar('despesa', '120.50', date(2026, 3, 20))
        self.assertEqual(_saldo_historico(self.u), Decimal('1379.50'))

    def test_lancamentos_do_dia_da_ancora_ficam_de_fora(self):
        """O saldo do extrato naquela data já contabiliza o que rolou no dia."""
        self.lancar('despesa', '80', date(2026, 3, 1))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 3, 1),
                                   valor=Decimal('1000.00'))
        self.assertEqual(_saldo_historico(self.u), Decimal('1000.00'))

    def test_vale_a_ancora_mais_recente(self):
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 1, 1),
                                   valor=Decimal('100'))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 5, 1),
                                   valor=Decimal('900'))
        self.lancar('receita', '50', date(2026, 6, 1))
        self.assertEqual(_saldo_historico(self.u), Decimal('950'))

    def test_desempate_no_mesmo_dia_pelo_ultimo_criado(self):
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 5, 1),
                                   valor=Decimal('100'))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 5, 1),
                                   valor=Decimal('700'))
        self.assertEqual(_saldo_historico(self.u), Decimal('700'))

    def test_ancora_nao_vaza_entre_usuarios(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        AjusteSaldo.objects.create(usuario=outro, data=date(2026, 1, 1),
                                   valor=Decimal('99999'))
        self.lancar('receita', '10', date(2026, 1, 2))
        self.assertEqual(_saldo_historico(self.u), Decimal('10'))

    def test_ancora_negativa(self):
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 3, 1),
                                   valor=Decimal('-300.00'))
        self.lancar('receita', '100', date(2026, 3, 5))
        self.assertEqual(_saldo_historico(self.u), Decimal('-200.00'))

    def test_ajuste_nao_mexe_nas_transacoes(self):
        """A âncora não inventa lançamento: médias e gráficos seguem intactos."""
        self.lancar('despesa', '250', date(2026, 2, 5))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 3, 1),
                                   valor=Decimal('9999'))
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 1)


class ViewAjusteTests(BaseAjuste):

    def setUp(self):
        super().setUp()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_registra_a_ancora(self):
        self.c.post('/saldo/ajustar/', {
            'data': '2026-03-01', 'valor': '1234.56', 'observacao': 'conferido',
        })
        ancora = AjusteSaldo.vigente(self.u)
        self.assertEqual(ancora.valor, Decimal('1234.56'))
        self.assertEqual(ancora.data, date(2026, 3, 1))
        self.assertEqual(ancora.observacao, 'conferido')

    def test_aceita_valor_com_virgula(self):
        self.c.post('/saldo/ajustar/', {'data': '2026-03-01', 'valor': '1.234,56'})
        self.assertEqual(AjusteSaldo.vigente(self.u).valor, Decimal('1234.56'))

    def test_recusa_valor_invalido(self):
        self.c.post('/saldo/ajustar/', {'data': '2026-03-01', 'valor': 'abc'})
        self.assertIsNone(AjusteSaldo.vigente(self.u))

    def test_recusa_data_futura(self):
        amanha = date.today() + timedelta(days=1)
        self.c.post('/saldo/ajustar/', {'data': amanha.isoformat(), 'valor': '10'})
        self.assertIsNone(AjusteSaldo.vigente(self.u))

    def test_sem_data_usa_hoje(self):
        self.c.post('/saldo/ajustar/', {'valor': '10'})
        self.assertEqual(AjusteSaldo.vigente(self.u).data, date.today())

    def test_desfazer_remove_a_ancora(self):
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 3, 1),
                                   valor=Decimal('500'))
        self.c.post('/saldo/ajustar/desfazer/')
        self.assertIsNone(AjusteSaldo.vigente(self.u))

    def test_desfazer_volta_uma_ancora_por_vez(self):
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 1, 1),
                                   valor=Decimal('100'))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 5, 1),
                                   valor=Decimal('900'))
        self.c.post('/saldo/ajustar/desfazer/')
        self.assertEqual(AjusteSaldo.vigente(self.u).valor, Decimal('100'))

    def test_get_nao_cria_nada(self):
        self.c.get('/saldo/ajustar/')
        self.assertIsNone(AjusteSaldo.vigente(self.u))

    def test_exige_login(self):
        self.c.logout()
        resposta = self.c.post('/saldo/ajustar/', {'valor': '10'})
        self.assertEqual(resposta.status_code, 302)
        self.assertIn('/entrar/', resposta['Location'])
        self.assertIsNone(AjusteSaldo.vigente(self.u))

    def test_nao_ajusta_saldo_alheio(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        AjusteSaldo.objects.create(usuario=outro, data=date(2026, 1, 1),
                                   valor=Decimal('500'))
        self.c.post('/saldo/ajustar/desfazer/')
        self.assertIsNotNone(AjusteSaldo.vigente(outro))

    def test_painel_mostra_o_saldo_ajustado(self):
        self.lancar('receita', '1000', date(2026, 1, 10))
        self.c.post('/saldo/ajustar/', {'data': '2026-03-01', 'valor': '4321.00'})
        pagina = self.c.get('/painel/').content.decode()
        self.assertIn('4.321,00', pagina)
        self.assertIn('Ajustado em 01/03/2026', pagina)

    def test_painel_sem_ancora_nao_fala_em_ajuste(self):
        pagina = self.c.get('/painel/').content.decode()
        self.assertIn('Histórico transações', pagina)
        self.assertNotIn('Ajustado em', pagina)
