"""Metas: as telas precisam abrir com ou sem parâmetros na URL.

O que estes testes protegem: `request.GET.x` usado como argumento de filtro ou
dentro de `{% with %}` **não falha em silêncio** como uma variável solta — ele
estoura com VariableDoesNotExist e derruba a página inteira. Foi assim que a
tela de nova meta e a de edição passaram a dar 500 sempre que não vinham do
link de sugestão.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import (Categoria, CategoriaEssencial, Essencial, Meta,
                               Transacao, TransacaoFixa)
from financeiro.views import sugestoes_de_limite

Usuario = get_user_model()


class TelasDeMetaTests(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.cat = Categoria.objects.filter(usuario=self.u, tipo='despesa').first()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)
        self.meta = Meta.objects.create(
            usuario=self.u, nome='Reserva', tipo='economia',
            valor_alvo=Decimal('1000'), data_inicio=date(2026, 1, 1),
        )

    def test_lista_abre(self):
        self.assertEqual(self.c.get('/metas/').status_code, 200)

    def test_nova_sem_parametro_nenhum(self):
        """O caminho normal: clicar em "nova meta" no topo da lista."""
        self.assertEqual(self.c.get('/metas/nova/').status_code, 200)

    def test_nova_com_parametros_parciais(self):
        self.assertEqual(self.c.get('/metas/nova/?tipo=economia').status_code, 200)
        self.assertEqual(self.c.get('/metas/nova/?valor=100').status_code, 200)

    def test_editar_abre(self):
        self.assertEqual(self.c.get(f'/metas/{self.meta.pk}/editar/').status_code, 200)

    def test_parametros_invalidos_nao_derrubam(self):
        for url in ('/metas/nova/?valor=abc',
                    '/metas/nova/?tipo=inventado',
                    '/metas/nova/?categoria=999999',
                    '/metas/nova/?categoria=nao-e-numero'):
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_categoria_de_outro_usuario_e_ignorada(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        alheia = Categoria.objects.filter(usuario=outro, tipo='despesa').first()
        pagina = self.c.get(f'/metas/nova/?categoria={alheia.pk}').content.decode()
        self.assertEqual(self.c.get(f'/metas/nova/?categoria={alheia.pk}').status_code, 200)
        self.assertNotIn(f'value="{alheia.pk}" selected', pagina)


class PreenchimentoDaSugestaoTests(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.cat = Categoria.objects.filter(usuario=self.u, tipo='despesa').first()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def test_link_da_sugestao_preenche_o_formulario(self):
        pagina = self.c.get(
            f'/metas/nova/?tipo=limite_gasto&categoria={self.cat.pk}&valor=734.43'
        ).content.decode()
        self.assertIn('value="734.43"', pagina)
        self.assertIn(f'value="{self.cat.pk}" selected', pagina)

    def test_meta_criada_a_partir_da_sugestao(self):
        self.c.post('/metas/nova/', {
            'nome': 'Limite em Alimentação', 'tipo': 'limite_gasto',
            'valor_alvo': '734.43', 'categoria': self.cat.pk,
            'data_inicio': '2026-08-01',
        })
        meta = Meta.objects.get(usuario=self.u)
        self.assertEqual(meta.valor_alvo, Decimal('734.43'))
        self.assertEqual(meta.categoria, self.cat)


class CalculoDaMetaTests(TestCase):
    """Os dois erros que faziam toda meta mentir."""

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.cat = Categoria.objects.filter(usuario=self.u, tipo='despesa').first()
        self.hoje = date.today()

    def lancar(self, tipo, valor, data, categoria=None):
        Transacao.objects.create(usuario=self.u, tipo=tipo, valor=Decimal(valor),
                                 data=data, descricao='x', categoria=categoria)

    def test_economia_desconta_as_despesas(self):
        """Recebeu 3000, gastou 2900: guardou 100, não 3000."""
        self.lancar('receita', '3000', self.hoje)
        self.lancar('despesa', '2900', self.hoje, self.cat)
        meta = Meta.objects.create(usuario=self.u, nome='Guardar', tipo='economia',
                                   valor_alvo=Decimal('1000'),
                                   data_inicio=self.hoje - timedelta(days=5))
        self.assertEqual(meta.valor_atual(), Decimal('100'))

    def test_economia_negativa_quando_gastou_mais(self):
        self.lancar('receita', '1000', self.hoje)
        self.lancar('despesa', '1500', self.hoje, self.cat)
        meta = Meta.objects.create(usuario=self.u, nome='Guardar', tipo='economia',
                                   valor_alvo=Decimal('500'),
                                   data_inicio=self.hoje - timedelta(days=5))
        self.assertEqual(meta.valor_atual(), Decimal('-500'))

    def test_meta_de_receita_continua_bruta(self):
        self.lancar('receita', '3000', self.hoje)
        self.lancar('despesa', '2900', self.hoje, self.cat)
        meta = Meta.objects.create(usuario=self.u, nome='Faturar', tipo='receita',
                                   valor_alvo=Decimal('3000'),
                                   data_inicio=self.hoje - timedelta(days=5))
        self.assertEqual(meta.valor_atual(), Decimal('3000'))

    def test_limite_mensal_ignora_meses_anteriores(self):
        """Gasta 300/mês com limite de 400: sempre dentro, nunca acumula."""
        for i in range(6):
            self.lancar('despesa', '300', self.hoje - timedelta(days=30 * i), self.cat)
        meta = Meta.objects.create(usuario=self.u, nome='Limite', tipo='limite_gasto',
                                   categoria=self.cat, valor_alvo=Decimal('400'),
                                   periodicidade='mensal',
                                   data_inicio=self.hoje - timedelta(days=200))
        self.assertEqual(meta.valor_atual(), Decimal('300'))
        self.assertEqual(meta.status_cor(), 'green')

    def test_limite_total_continua_acumulando(self):
        for i in range(6):
            self.lancar('despesa', '300', self.hoje - timedelta(days=30 * i), self.cat)
        meta = Meta.objects.create(usuario=self.u, nome='Teto da reforma',
                                   tipo='limite_gasto', categoria=self.cat,
                                   valor_alvo=Decimal('400'), periodicidade='total',
                                   data_inicio=self.hoje - timedelta(days=200))
        self.assertEqual(meta.valor_atual(), Decimal('1800'))

    def test_janela_nao_comeca_antes_da_meta(self):
        """Meta criada hoje não pode contar o gasto de ontem."""
        self.lancar('despesa', '999', self.hoje - timedelta(days=1), self.cat)
        meta = Meta.objects.create(usuario=self.u, nome='Limite', tipo='limite_gasto',
                                   categoria=self.cat, valor_alvo=Decimal('400'),
                                   data_inicio=self.hoje)
        inicio, _ = meta.janela()
        self.assertEqual(inicio, self.hoje)
        self.assertEqual(meta.valor_atual(), Decimal('0'))

    def test_padrao_e_mensal(self):
        meta = Meta.objects.create(usuario=self.u, nome='M', tipo='limite_gasto',
                                   categoria=self.cat, valor_alvo=Decimal('100'),
                                   data_inicio=self.hoje)
        self.assertEqual(meta.periodicidade, 'mensal')


class SugestoesTests(TestCase):
    """Sugerir limite onde gastar menos não é uma escolha é pedir o impossível."""

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.hoje = date.today()
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def categoria(self, nome):
        cat, _ = Categoria.objects.get_or_create(usuario=self.u, nome=nome, tipo='despesa')
        return cat

    def gastar_por_mes(self, categoria, valores):
        """Um lançamento em cada um dos últimos meses, do mais recente ao mais antigo.

        Dia 1 de propósito: qualquer dia depois de hoje cairia fora da consulta,
        que só olha até a data corrente.
        """
        for i, valor in enumerate(valores):
            mes = self.hoje.month - i
            ano = self.hoje.year
            while mes <= 0:
                mes += 12
                ano -= 1
            Transacao.objects.create(
                usuario=self.u, tipo='despesa', categoria=categoria,
                valor=Decimal(str(valor)), data=date(ano, mes, 1), descricao='x',
            )

    def sugeridas(self):
        return {s['categoria_nome']: s for s in sugestoes_de_limite(self.u)}

    def test_gasto_que_varia_e_sugerido(self):
        self.gastar_por_mes(self.categoria('Lazer'), [400, 250, 520, 300])
        self.assertIn('Lazer', self.sugeridas())

    def test_alvo_e_o_melhor_mes(self):
        self.gastar_por_mes(self.categoria('Lazer'), [400, 250, 520, 300])
        s = self.sugeridas()['Lazer']
        self.assertEqual(s['limite_sugerido'], 250.0)
        self.assertEqual(s['media_mensal'], 367.5)
        self.assertEqual(s['economia_mes'], 117.5)

    def test_gasto_que_nao_varia_fica_de_fora(self):
        """Aluguel de 667,66 todo mês: o dado já diz que é contratado."""
        self.gastar_por_mes(self.categoria('Moradia'), [667.66, 667.66, 667.66, 667.66])
        self.assertNotIn('Moradia', self.sugeridas())

    def test_categoria_com_recorrente_fica_de_fora(self):
        cat = self.categoria('Internet')
        self.gastar_por_mes(cat, [99, 130, 80, 150])          # variaria, se pudesse
        TransacaoFixa.objects.create(
            usuario=self.u, tipo='despesa', descricao='Internet', categoria=cat,
            valor=Decimal('99'), frequencia='mensal', data_inicio=self.hoje, ativa=True,
        )
        self.assertNotIn('Internet', self.sugeridas())

    def test_recorrente_inativa_nao_bloqueia(self):
        cat = self.categoria('Lazer')
        self.gastar_por_mes(cat, [400, 250, 520, 300])
        TransacaoFixa.objects.create(
            usuario=self.u, tipo='despesa', descricao='antiga', categoria=cat,
            valor=Decimal('99'), frequencia='mensal', data_inicio=self.hoje, ativa=False,
        )
        self.assertIn('Lazer', self.sugeridas())

    def test_essencial_nao_variavel_fica_de_fora(self):
        CategoriaEssencial.sincronizar_catalogo()
        cat_cat = CategoriaEssencial.objects.get(slug='saude')      # variavel=False
        self.assertFalse(cat_cat.variavel)
        Essencial.objects.create(usuario=self.u, categoria=cat_cat,
                                 valor=Decimal('300'), data_inicio=self.hoje)
        cat = self.categoria(cat_cat.nome)
        self.gastar_por_mes(cat, [300, 180, 420, 250])
        self.assertNotIn(cat_cat.nome, self.sugeridas())

    def test_poucos_meses_nao_sugere(self):
        """Dois meses não dizem se o gasto varia ou se foi exceção."""
        self.gastar_por_mes(self.categoria('Lazer'), [400, 250])
        self.assertNotIn('Lazer', self.sugeridas())

    def test_categoria_com_meta_nao_e_sugerida(self):
        cat = self.categoria('Lazer')
        self.gastar_por_mes(cat, [400, 250, 520, 300])
        Meta.objects.create(usuario=self.u, nome='Limite', tipo='limite_gasto',
                            categoria=cat, valor_alvo=Decimal('300'), data_inicio=self.hoje)
        self.assertNotIn('Lazer', self.sugeridas())

    def test_ordenadas_pela_economia_possivel(self):
        self.gastar_por_mes(self.categoria('Lazer'), [400, 250, 520, 300])
        self.gastar_por_mes(self.categoria('Alimentação'), [900, 400, 1100, 800])
        nomes = [s['categoria_nome'] for s in sugestoes_de_limite(self.u)]
        self.assertEqual(nomes[0], 'Alimentação')

    def test_sem_gastos_nao_ha_sugestao(self):
        self.assertEqual(sugestoes_de_limite(self.u), [])

    def test_nao_vaza_entre_usuarios(self):
        self.gastar_por_mes(self.categoria('Lazer'), [400, 250, 520, 300])
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        self.assertEqual(sugestoes_de_limite(outro), [])
