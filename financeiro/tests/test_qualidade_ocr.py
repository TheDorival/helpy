"""Robustez da leitura por OCR: linhas descartadas e escolha da melhor tentativa."""

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.importacao import parse_linhas_caixa
from financeiro.views import _qualidade_leitura

Usuario = get_user_model()

# Linha com o valor destruído pelo OCR: sobra apenas o saldo
LINHA_ILEGIVEL = '01/08/2026 - 03:04:10 000000 CORRECAO MONETARIA goocC 812,11 C'
LINHA_BOA = '01/08/2026 - 12:21:57 011221 COMPRA CARTAO DEBITO Unicompra 2,59 D 809,53 C'
LINHA_BOA_2 = '01/08/2026 - 03:04:10 000000 CREDITO JUROS 0,01 C 812,12 C'


class DescartesTests(TestCase):
    """Um lançamento ilegível não pode sumir sem deixar rastro."""

    def test_conta_linha_descartada(self):
        descartes = []
        parse_linhas_caixa([LINHA_ILEGIVEL, LINHA_BOA], descartes)
        self.assertEqual(len(descartes), 1)
        self.assertIn('CORRECAO MONETARIA', descartes[0])

    def test_nao_conta_linha_valida(self):
        descartes = []
        parse_linhas_caixa([LINHA_BOA, LINHA_BOA_2], descartes)
        self.assertEqual(descartes, [])

    def test_linha_de_valor_zero_nao_e_descarte(self):
        """Valor zero é lançamento sem efeito, não falha de leitura."""
        descartes = []
        parse_linhas_caixa([
            '01/08/2026 - 03:04:10 000000 CORRECAO MONETARIA 0,00 C 812,11 C',
            LINHA_BOA,
        ], descartes)
        self.assertEqual(descartes, [])

    def test_parametro_opcional(self):
        """Sem a lista, o parser funciona igual — compatível com quem já chama."""
        self.assertEqual(len(parse_linhas_caixa([LINHA_ILEGIVEL, LINHA_BOA])), 1)


class QualidadeTests(TestCase):

    def test_nota_considera_descartadas(self):
        """10 linhas no extrato, 2 ilegíveis: 8 de 9 verificáveis."""
        conf = {'total': 8, 'conferem': 8, 'divergem': 0, 'descartadas': 2}
        self.assertAlmostEqual(_qualidade_leitura(conf), 8 / 9)

    def test_nota_maxima(self):
        conf = {'total': 10, 'conferem': 10, 'divergem': 0, 'descartadas': 0}
        self.assertEqual(_qualidade_leitura(conf), 1.0)

    def test_ultima_linha_nao_penaliza_extrato_curto(self):
        """Com 3 linhas, 2 conferindo é o máximo possível."""
        conf = {'total': 3, 'conferem': 2, 'divergem': 0, 'descartadas': 0}
        self.assertEqual(_qualidade_leitura(conf), 1.0)

    def test_divergencias_derrubam_a_nota(self):
        conf = {'total': 10, 'conferem': 5, 'divergem': 4, 'descartadas': 0}
        self.assertAlmostEqual(_qualidade_leitura(conf), 5 / 9)

    def test_leitura_vazia(self):
        self.assertEqual(_qualidade_leitura({'total': 0, 'conferem': 0, 'descartadas': 0}), 0.0)


class SegundaTentativaTests(TestCase):
    """O navegador pode reenviar uma leitura melhor; a melhor vence."""

    def setUp(self):
        self.u = Usuario.objects.create_user(username='ocr', password='x')
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def _enviar(self, linhas, tentativa=1):
        return self.c.post(
            '/importar/pdf/',
            data=json.dumps({'arquivo_nome': 'e.pdf', 'linhas': linhas, 'tentativa': tentativa}),
            content_type='application/json',
        ).json()

    def test_sugere_repetir_quando_a_leitura_e_ruim(self):
        resposta = self._enviar([LINHA_ILEGIVEL, LINHA_BOA])
        self.assertTrue(resposta['ok'])
        self.assertTrue(resposta['tentar_de_novo'])
        self.assertLess(resposta['qualidade'], 0.8)

    def test_nao_sugere_repetir_quando_esta_boa(self):
        linhas = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 570,00 D 1.014,11 C',
            '31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa 7,49 D 1.584,11 C',
        ]
        resposta = self._enviar(linhas)
        self.assertFalse(resposta['tentar_de_novo'])

    def test_segunda_tentativa_melhor_substitui(self):
        self._enviar([LINHA_ILEGIVEL, LINHA_BOA], tentativa=1)
        melhores = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 570,00 D 1.014,11 C',
            '31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa 7,49 D 1.584,11 C',
        ]
        resposta = self._enviar(melhores, tentativa=2)
        self.assertTrue(resposta['ok'])
        self.assertFalse(resposta.get('usou_anterior'))

        pagina = self.c.get('/importar/revisar/').content.decode()
        self.assertIn('779,49', pagina)          # total da segunda leitura

    def test_segunda_tentativa_pior_e_ignorada(self):
        boas = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 570,00 D 1.014,11 C',
            '31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa 7,49 D 1.584,11 C',
        ]
        self._enviar(boas, tentativa=1)
        resposta = self._enviar([LINHA_ILEGIVEL, LINHA_BOA], tentativa=2)
        self.assertTrue(resposta['ok'])
        self.assertTrue(resposta['usou_anterior'])

        pagina = self.c.get('/importar/revisar/').content.decode()
        self.assertIn('779,49', pagina)          # manteve a primeira leitura
        self.assertNotIn('CORRECAO MONETARIA', pagina)

    def test_revisao_avisa_sobre_linhas_nao_reconhecidas(self):
        self._enviar([LINHA_ILEGIVEL, LINHA_BOA, LINHA_BOA_2])
        pagina = self.c.get('/importar/revisar/').content.decode()
        self.assertIn('Não reconhecidas', pagina)
        self.assertIn('CORRECAO MONETARIA', pagina)
