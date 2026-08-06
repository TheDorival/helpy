"""Filtro de dados sensíveis enviados ao Sentry.

Este é um app financeiro: nenhum relatório de erro pode carregar valores,
descrições de lançamentos ou cookies de sessão.
"""

import importlib

from django.test import SimpleTestCase


def _carregar_filtro():
    """Importa a função direto do módulo de produção, sem ativar o Sentry."""
    modulo = importlib.import_module('helpy.settings.prod')
    return modulo._limpar_dados_sensiveis


class FiltroSentryTests(SimpleTestCase):

    def setUp(self):
        self.limpar = _carregar_filtro()

    def _evento(self):
        return {
            'request': {
                'url': 'https://helpy/importar/revisar/',
                'method': 'POST',
                'data': {'valor_0': '3500.00', 'descricao_0': 'Salário de agosto'},
                'cookies': {'sessionid': 'abc123'},
                'headers': {
                    'Cookie': 'sessionid=abc123',
                    'Authorization': 'Bearer token',
                    'User-Agent': 'Chrome',
                },
            },
            'message': 'Erro qualquer',
        }

    def test_remove_corpo_da_requisicao(self):
        limpo = self.limpar(self._evento())
        self.assertNotIn('data', limpo['request'])

    def test_remove_cookies(self):
        limpo = self.limpar(self._evento())
        self.assertNotIn('cookies', limpo['request'])
        self.assertNotIn('Cookie', limpo['request']['headers'])

    def test_remove_autorizacao(self):
        limpo = self.limpar(self._evento())
        self.assertNotIn('Authorization', limpo['request']['headers'])

    def test_preserva_o_que_ajuda_a_diagnosticar(self):
        limpo = self.limpar(self._evento())
        self.assertEqual(limpo['request']['url'], 'https://helpy/importar/revisar/')
        self.assertEqual(limpo['request']['method'], 'POST')
        self.assertEqual(limpo['request']['headers']['User-Agent'], 'Chrome')
        self.assertEqual(limpo['message'], 'Erro qualquer')

    def test_evento_sem_requisicao_nao_quebra(self):
        self.assertEqual(self.limpar({'message': 'erro solto'}), {'message': 'erro solto'})

    def test_nenhum_valor_monetario_sobrevive(self):
        texto = str(self.limpar(self._evento()))
        self.assertNotIn('3500.00', texto)
        self.assertNotIn('Salário de agosto', texto)
        self.assertNotIn('abc123', texto)
