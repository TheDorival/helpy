"""Vale como essencial: o crédito mensal cai no bolso do vale, não na conta.

Se caísse na conta, o saldo bancário passaria a divergir do extrato todo mês —
justamente o que a separação por bolsos existe para evitar.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import (CATALOGO_ESSENCIAIS, CategoriaEssencial, Essencial,
                               Transacao, TransacaoFixa)
from financeiro.views import sincronizar_fixas
from helpy.views import _saldo_historico

Usuario = get_user_model()


class CatalogoTests(TestCase):

    def setUp(self):
        CategoriaEssencial.sincronizar_catalogo()

    def test_vale_existe_no_catalogo(self):
        cat = CategoriaEssencial.objects.get(slug='vale_alimentacao')
        self.assertEqual(cat.tipo, 'receita')
        self.assertEqual(cat.conta, 'vale')

    def test_vale_e_a_unica_categoria_restrita(self):
        restritas = [c.slug for c in CategoriaEssencial.objects.all() if c.restrita]
        self.assertEqual(restritas, ['vale_alimentacao'])

    def test_demais_categorias_sao_bancarias(self):
        outras = CategoriaEssencial.objects.exclude(slug='vale_alimentacao')
        self.assertTrue(all(c.conta == 'banco' for c in outras))

    def test_catalogo_tem_conta_em_toda_entrada(self):
        for entrada in CATALOGO_ESSENCIAIS:
            self.assertEqual(len(entrada), 10, entrada[0])

    def test_sincronizar_e_idempotente(self):
        antes = CategoriaEssencial.objects.count()
        CategoriaEssencial.sincronizar_catalogo()
        self.assertEqual(CategoriaEssencial.objects.count(), antes)


class ValeComoEssencialTests(TestCase):

    def setUp(self):
        CategoriaEssencial.sincronizar_catalogo()
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def _ativar_vale(self, valor='600', dia='5'):
        return self.c.post('/essenciais/vale_alimentacao/ativar/', {
            'valor': valor, 'dia_vencimento': dia, 'observacao': '',
        })

    def test_ativar_cria_recorrente_no_bolso_do_vale(self):
        self._ativar_vale()
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='vale_alimentacao')
        self.assertIsNotNone(ess.transacao_fixa)
        self.assertEqual(ess.transacao_fixa.conta, 'vale')
        self.assertEqual(ess.transacao_fixa.tipo, 'receita')

    def test_ocorrencias_nascem_no_bolso_do_vale(self):
        self._ativar_vale()
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='vale_alimentacao')
        TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
            data_inicio=date(2026, 1, 5), ultima_geracao=None,
        )
        sincronizar_fixas(self.u, limite=date(2026, 3, 31))

        geradas = Transacao.objects.filter(usuario=self.u, origem_fixa=ess.transacao_fixa)
        self.assertTrue(geradas.exists())
        self.assertTrue(all(t.conta == 'vale' for t in geradas))

    def test_credito_do_vale_nao_infla_a_conta(self):
        """O ponto todo: o saldo bancário continua batendo com o extrato."""
        self._ativar_vale()
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='vale_alimentacao')
        TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
            data_inicio=date(2026, 1, 5), ultima_geracao=None,
        )
        sincronizar_fixas(self.u, limite=date(2026, 3, 31))

        self.assertEqual(_saldo_historico(self.u, 'banco'), Decimal('0'))
        self.assertGreater(_saldo_historico(self.u, 'vale'), Decimal('0'))

    def test_gasto_de_vale_consome_o_proprio_bolso(self):
        self._ativar_vale()
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='vale_alimentacao')
        TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
            data_inicio=date(2026, 1, 5), ultima_geracao=None,
        )
        sincronizar_fixas(self.u, limite=date(2026, 1, 31))
        Transacao.objects.create(usuario=self.u, tipo='despesa', valor=Decimal('45'),
                                 data=date(2026, 1, 10), conta='vale', descricao='Almoço')

        self.assertEqual(_saldo_historico(self.u, 'vale'), Decimal('555'))
        self.assertEqual(_saldo_historico(self.u, 'banco'), Decimal('0'))

    def test_vale_fica_no_restrito_do_painel(self):
        self._ativar_vale()
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='vale_alimentacao')
        TransacaoFixa.objects.filter(pk=ess.transacao_fixa_id).update(
            data_inicio=date(2026, 1, 5), ultima_geracao=None,
        )

        # O painel sincroniza as recorrentes até hoje, então o total depende da
        # data em que o teste roda — o que importa é onde o dinheiro caiu.
        contexto = self.c.get('/painel/').context
        self.assertEqual(contexto['saldo_disponivel'], 0.0)
        self.assertGreater(contexto['saldo_restrito'], 0.0)
        self.assertEqual(contexto['saldo_restrito'],
                         float(_saldo_historico(self.u, 'vale')))

    def test_edicao_preserva_o_bolso(self):
        self._ativar_vale()
        self.c.post('/essenciais/vale_alimentacao/editar/', {
            'valor': '700', 'dia_vencimento': '10', 'observacao': '', 'escopo': 'futuras',
        })
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='vale_alimentacao')
        self.assertEqual(ess.transacao_fixa.conta, 'vale')
        self.assertEqual(ess.transacao_fixa.valor, Decimal('700'))

    def test_salario_continua_no_banco(self):
        self.c.post('/essenciais/salario/ativar/', {
            'valor': '3000', 'dia_vencimento': '5', 'tipo_salario': 'fixo',
            'freq_pagamento': 'mensal', 'observacao': '',
        })
        ess = Essencial.objects.get(usuario=self.u, categoria__slug='salario')
        self.assertEqual(ess.transacao_fixa.conta, 'banco')

    def test_pagina_de_essenciais_sinaliza_o_bolso(self):
        self._ativar_vale()
        pagina = self.c.get('/essenciais/').content.decode()
        self.assertIn('Vale alimentação/refeição', pagina)
