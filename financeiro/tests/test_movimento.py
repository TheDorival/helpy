"""Marcação de movimento: animação é enfeite, então nada pode depender dela.

A regra que estes testes protegem: o valor correto tem que estar na página
mesmo sem JavaScript, e a preferência de animação reduzida tem que chegar ao
navegador. Animação quebrada é chato; número errado num app financeiro, não.
"""

import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import Categoria, Meta, Transacao

Usuario = get_user_model()


class MarcacaoDeMovimentoTests(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='mov', password='x')
        self.cat = Categoria.objects.create(usuario=self.u, nome='Geral', tipo='despesa')
        Transacao.objects.create(usuario=self.u, tipo='receita', valor=Decimal('4321.55'),
                                 data=date.today(), descricao='Entrada')
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def painel(self):
        return self.c.get('/painel/').content.decode()

    def test_valor_visivel_continua_localizado(self):
        """Sem JavaScript o número tem que aparecer certo, em pt-BR."""
        self.assertIn('4.321,55', self.painel())

    def test_data_conta_sem_localizacao(self):
        """`parseFloat` não entende vírgula decimal — o alvo vai sem localizar."""
        valores = re.findall(r'data-conta="([^"]*)"', self.painel())
        self.assertTrue(valores)
        for v in valores:
            self.assertNotIn(',', v, f'{v} quebraria o parseFloat')
            self.assertRegex(v, r'^-?\d+\.\d{2}$')

    def test_saldo_marcado_para_contar(self):
        valores = re.findall(r'data-conta="([^"]*)"', self.painel())
        self.assertIn('4321.55', valores)

    def test_barra_leva_a_largura_final(self):
        """A largura fica no style e no data-barra: sem JS a barra já nasce certa."""
        Meta.objects.create(usuario=self.u, nome='Reserva', tipo='economia',
                            valor_alvo=Decimal('1000'), data_inicio=date(2026, 1, 1))
        pagina = self.c.get('/metas/').content.decode()
        for largura, dado in re.findall(
            r'data-barra="(\d+)"[^>]*style="width: (\d+)%"', pagina,
        ):
            self.assertEqual(largura, dado)

    def _tag_html(self, pagina):
        """Só a tag de abertura — a folha de estilo também cita o atributo."""
        return re.search(r'<html.*?>', pagina, re.DOTALL).group(0)

    def test_preferencia_de_animacao_chega_ao_html(self):
        self.assertNotIn('data-reduzir-animacoes', self._tag_html(self.painel()))

        self.u.reduzir_animacoes = True
        self.u.save(update_fields=['reduzir_animacoes'])
        self.assertIn('data-reduzir-animacoes="1"', self._tag_html(self.painel()))

    def test_movimento_reduzido_devolve_a_opacidade(self):
        """Anular a animação sem isso deixaria a página em branco."""
        pagina = self.painel()
        self.assertIn('data-reduzir-animacoes="1"] .entra', pagina)
        self.assertIn('.escalona > * { opacity: 1 !important; }', pagina)

    def test_transicao_de_pagina_declarada(self):
        self.assertIn('@view-transition', self.painel())

    def test_escalonamento_disponivel(self):
        pagina = self.painel()
        self.assertIn('.escalona', pagina)
        self.assertIn('barra-cresce', pagina)
