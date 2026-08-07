"""Metas: as telas precisam abrir com ou sem parâmetros na URL.

O que estes testes protegem: `request.GET.x` usado como argumento de filtro ou
dentro de `{% with %}` **não falha em silêncio** como uma variável solta — ele
estoura com VariableDoesNotExist e derruba a página inteira. Foi assim que a
tela de nova meta e a de edição passaram a dar 500 sempre que não vinham do
link de sugestão.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from financeiro.models import Categoria, Meta, Transacao

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


class SugestoesTests(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.c = Client(SERVER_NAME='localhost')
        self.c.force_login(self.u)

    def gastar(self, categoria, valor, data):
        Transacao.objects.create(usuario=self.u, tipo='despesa', categoria=categoria,
                                 valor=Decimal(valor), data=data, descricao='x')

    def test_categoria_com_meta_nao_e_sugerida(self):
        cat = Categoria.objects.filter(usuario=self.u, tipo='despesa').first()
        hoje = date.today()
        self.gastar(cat, '300', hoje)
        Meta.objects.create(usuario=self.u, nome='Limite', tipo='limite_gasto',
                            categoria=cat, valor_alvo=Decimal('300'), data_inicio=hoje)
        contexto = self.c.get('/metas/').context
        sugeridas = [s['categoria_id'] for s in contexto['sugestoes']]
        self.assertNotIn(cat.pk, sugeridas)

    def test_sem_gastos_nao_ha_sugestao(self):
        self.assertEqual(list(self.c.get('/metas/').context['sugestoes']), [])
