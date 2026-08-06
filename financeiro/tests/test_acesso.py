"""Autenticação obrigatória e isolamento entre usuários."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import Categoria, RegraCategoria, Transacao, TransacaoFixa

Usuario = get_user_model()

PAGINAS = [
    '/painel/', '/resumo/', '/receitas/', '/despesas/', '/recorrentes/',
    '/categorias/', '/entidades/', '/graficos/', '/metas/', '/emprestimos/',
    '/essenciais/', '/historico/', '/importar/', '/regras/',
    '/configuracoes/conta/', '/configuracoes/preferencias/', '/configuracoes/aparencia/',
]


class AcessoTests(TestCase):

    def setUp(self):
        self.c = Client(SERVER_NAME='localhost')

    def test_paginas_exigem_login(self):
        for url in PAGINAS:
            with self.subTest(url=url):
                resposta = self.c.get(url)
                self.assertEqual(resposta.status_code, 302)
                self.assertIn('/entrar/', resposta['Location'])

    def test_paginas_abrem_para_usuario_logado(self):
        u = Usuario.objects.create_user(username='visitante', password='x')
        self.c.force_login(u)
        for url in PAGINAS:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)


class IsolamentoTests(TestCase):
    """Um usuário nunca deve ver ou alterar dados de outro."""

    def setUp(self):
        self.dono = Usuario.objects.create_user(username='dono', password='x')
        self.intruso = Usuario.objects.create_user(username='intruso', password='x')
        self.transacao = Transacao.objects.create(
            usuario=self.dono, tipo='despesa', descricao='Segredo',
            valor=Decimal('99'), data=date(2026, 7, 1),
        )
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.intruso)

    def test_nao_lista_transacao_alheia(self):
        resposta = self.c.get('/despesas/?mes=7&ano=2026')
        self.assertNotContains(resposta, 'Segredo')

    def test_nao_edita_transacao_alheia(self):
        self.assertEqual(self.c.get(f'/transacao/{self.transacao.pk}/editar/').status_code, 404)

    def test_nao_exclui_transacao_alheia(self):
        self.c.post(f'/transacao/{self.transacao.pk}/excluir/')
        self.assertTrue(Transacao.objects.filter(pk=self.transacao.pk).exists())

    def test_nao_edita_recorrente_alheia(self):
        tf = TransacaoFixa.objects.create(
            usuario=self.dono, tipo='despesa', descricao='Aluguel',
            valor=Decimal('1000'), frequencia='mensal', data_inicio=date(2026, 7, 1),
        )
        self.assertEqual(self.c.get(f'/recorrentes/{tf.pk}/editar/').status_code, 404)

    def test_nao_edita_regra_alheia(self):
        cat = Categoria.objects.create(usuario=self.dono, nome='Casa', tipo='despesa')
        regra = RegraCategoria.objects.create(
            usuario=self.dono, termo='ALUGUEL', categoria=cat, aplica_a='despesa',
        )
        self.assertEqual(self.c.get(f'/regras/{regra.pk}/editar/').status_code, 404)
