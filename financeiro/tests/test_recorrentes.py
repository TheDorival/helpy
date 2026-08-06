"""Geração, projeção e alteração de transações recorrentes."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from financeiro.models import Categoria, Transacao, TransacaoFixa
from financeiro.views import (_aplicar_escopo, _datas_ja_geradas, projetar_fixas,
                              sincronizar_fixas)

Usuario = get_user_model()


def criar_usuario(nome='tester', **extra):
    return Usuario.objects.create_user(username=nome, password='segredo', **extra)


class GeracaoTests(TestCase):

    def setUp(self):
        self.u = criar_usuario()
        self.hoje = date.today()

    def _fixa(self, **kwargs):
        padrao = dict(
            usuario=self.u, tipo='despesa', descricao='Aluguel',
            valor=Decimal('1200'), frequencia='mensal', ativa=True,
        )
        padrao.update(kwargs)
        return TransacaoFixa.objects.create(**padrao)

    def test_gera_ocorrencias_ate_hoje(self):
        inicio = self.hoje.replace(day=1) - timedelta(days=70)
        self._fixa(data_inicio=inicio)
        sincronizar_fixas(self.u)
        geradas = Transacao.objects.filter(usuario=self.u)
        self.assertGreaterEqual(geradas.count(), 2)
        self.assertTrue(all(t.data <= self.hoje for t in geradas))

    def test_nao_gera_alem_de_hoje(self):
        self._fixa(data_inicio=self.hoje + timedelta(days=5))
        sincronizar_fixas(self.u)
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 0)

    def test_sincronizar_e_idempotente(self):
        self._fixa(data_inicio=self.hoje - timedelta(days=40))
        sincronizar_fixas(self.u)
        antes = Transacao.objects.filter(usuario=self.u).count()
        sincronizar_fixas(self.u)
        sincronizar_fixas(self.u)
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), antes)

    def test_vincula_transacao_a_recorrente(self):
        tf = self._fixa(data_inicio=self.hoje - timedelta(days=10))
        sincronizar_fixas(self.u)
        t = Transacao.objects.filter(usuario=self.u).first()
        self.assertEqual(t.origem_fixa_id, tf.pk)

    def test_respeita_data_fim(self):
        inicio = self.hoje - timedelta(days=70)
        self._fixa(data_inicio=inicio, data_fim=inicio + timedelta(days=5))
        sincronizar_fixas(self.u)
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 1)

    def test_recorrente_inativa_nao_gera(self):
        self._fixa(data_inicio=self.hoje - timedelta(days=40), ativa=False)
        sincronizar_fixas(self.u)
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 0)

    def test_nao_repete_ocorrencia_ja_materializada(self):
        """Cenário do reagendamento: controle de geração zerado, data já usada."""
        tf = self._fixa(data_inicio=self.hoje - timedelta(days=30))
        sincronizar_fixas(self.u)
        total = Transacao.objects.filter(usuario=self.u).count()

        TransacaoFixa.objects.filter(pk=tf.pk).update(ultima_geracao=None)
        sincronizar_fixas(self.u)

        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), total)

    def test_dia_util_recalcula_a_cada_mes(self):
        """5º dia útil muda de dia conforme o mês — não pode repetir o dia fixo."""
        tf = self._fixa(
            tipo='receita', descricao='Salário', valor=Decimal('2000'),
            data_inicio=date(2026, 8, 7), dia_util_n=5,
        )
        datas = [tf.data_inicio]
        d = tf.data_inicio
        for _ in range(3):
            d = tf.avancar(d, 'com_feriados')
            datas.append(d)
        self.assertEqual(datas, [
            date(2026, 8, 7), date(2026, 9, 8), date(2026, 10, 7), date(2026, 11, 9),
        ])

    def test_datas_ja_geradas_agrupa_por_recorrente(self):
        tf = self._fixa(data_inicio=self.hoje - timedelta(days=40))
        sincronizar_fixas(self.u)
        mapa = _datas_ja_geradas(self.u)
        self.assertIn(tf.pk, mapa)
        self.assertTrue(mapa[tf.pk])


class ProjecaoTests(TestCase):

    def setUp(self):
        self.u = criar_usuario('proj')
        self.hoje = date.today()
        self.tf = TransacaoFixa.objects.create(
            usuario=self.u, tipo='despesa', descricao='Internet',
            valor=Decimal('100'), frequencia='mensal', ativa=True,
            data_inicio=self.hoje - timedelta(days=40),
        )
        sincronizar_fixas(self.u)

    def test_projeta_sem_gravar_no_banco(self):
        antes = Transacao.objects.filter(usuario=self.u).count()
        previstas = projetar_fixas(self.u, self.hoje + timedelta(days=1),
                                   self.hoje + timedelta(days=200))
        self.assertTrue(previstas)
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), antes)

    def test_projecao_comeca_depois_do_ultimo_gerado(self):
        previstas = projetar_fixas(self.u, self.hoje + timedelta(days=1),
                                   self.hoje + timedelta(days=200))
        self.assertTrue(all(p['data'] > self.hoje for p in previstas))

    def test_projecao_nao_repete_data_ja_materializada(self):
        """Data já lançada não pode voltar como previsão."""
        futura = self.hoje + timedelta(days=3)
        Transacao.objects.create(
            usuario=self.u, tipo='despesa', descricao='Internet',
            valor=Decimal('100'), data=futura, origem_fixa=self.tf,
        )
        TransacaoFixa.objects.filter(pk=self.tf.pk).update(
            data_inicio=futura, ultima_geracao=None,
        )
        previstas = projetar_fixas(self.u, self.hoje, self.hoje + timedelta(days=200))
        self.assertNotIn(futura, [p['data'] for p in previstas])

    def test_filtra_por_tipo(self):
        TransacaoFixa.objects.create(
            usuario=self.u, tipo='receita', descricao='Bolsa',
            valor=Decimal('500'), frequencia='mensal', ativa=True,
            data_inicio=self.hoje + timedelta(days=2),
        )
        receitas = projetar_fixas(self.u, self.hoje, self.hoje + timedelta(days=100),
                                  tipo='receita')
        self.assertTrue(receitas)
        self.assertTrue(all(p['tipo'] == 'receita' for p in receitas))


class EscopoAlteracaoTests(TestCase):
    """Ao editar uma recorrente: só futuras, período atual ou todas."""

    def setUp(self):
        self.u = criar_usuario('escopo')
        self.hoje = date.today()
        self.tf = TransacaoFixa.objects.create(
            usuario=self.u, tipo='despesa', descricao='Aluguel',
            valor=Decimal('1000'), frequencia='mensal', ativa=True,
            data_inicio=self.hoje - timedelta(days=70),
        )
        sincronizar_fixas(self.u)
        self.total = Transacao.objects.filter(usuario=self.u).count()

    def _valores(self):
        return sorted(t.valor for t in Transacao.objects.filter(usuario=self.u))

    def test_escopo_futuras_nao_altera_nada(self):
        antes = self._valores()
        TransacaoFixa.objects.filter(pk=self.tf.pk).update(valor=Decimal('1500'))
        self.tf.refresh_from_db()
        alteradas = _aplicar_escopo(self.tf, 'futuras', self.u)
        self.assertEqual(alteradas, 0)
        self.assertEqual(self._valores(), antes)

    def test_escopo_todas_reescreve_tudo(self):
        TransacaoFixa.objects.filter(pk=self.tf.pk).update(valor=Decimal('1500'))
        self.tf.refresh_from_db()
        alteradas = _aplicar_escopo(self.tf, 'todas', self.u)
        self.assertEqual(alteradas, self.total)
        self.assertTrue(all(v == Decimal('1500') for v in self._valores()))

    def test_escopo_atuais_preserva_meses_anteriores(self):
        atual = self.hoje.replace(day=1)
        Transacao.objects.create(
            usuario=self.u, tipo='despesa', descricao='Aluguel',
            valor=Decimal('1000'), data=atual, origem_fixa=self.tf,
        )
        TransacaoFixa.objects.filter(pk=self.tf.pk).update(valor=Decimal('1500'))
        self.tf.refresh_from_db()
        _aplicar_escopo(self.tf, 'atuais', self.u)

        recentes = Transacao.objects.filter(usuario=self.u, data__gte=atual)
        antigas = Transacao.objects.filter(usuario=self.u, data__lt=atual)
        self.assertTrue(all(t.valor == Decimal('1500') for t in recentes))
        self.assertTrue(all(t.valor == Decimal('1000') for t in antigas))

    def test_escopo_nao_altera_datas(self):
        datas_antes = sorted(t.data for t in Transacao.objects.filter(usuario=self.u))
        TransacaoFixa.objects.filter(pk=self.tf.pk).update(valor=Decimal('1500'))
        self.tf.refresh_from_db()
        _aplicar_escopo(self.tf, 'todas', self.u)
        datas_depois = sorted(t.data for t in Transacao.objects.filter(usuario=self.u))
        self.assertEqual(datas_antes, datas_depois)

    def test_escopo_nao_vaza_para_outro_usuario(self):
        outro = criar_usuario('vizinho')
        tf_outro = TransacaoFixa.objects.create(
            usuario=outro, tipo='despesa', descricao='Aluguel',
            valor=Decimal('1000'), frequencia='mensal', ativa=True,
            data_inicio=self.hoje - timedelta(days=40),
        )
        sincronizar_fixas(outro)
        TransacaoFixa.objects.filter(pk=self.tf.pk).update(valor=Decimal('1500'))
        self.tf.refresh_from_db()
        _aplicar_escopo(self.tf, 'todas', self.u)
        self.assertTrue(all(
            t.valor == Decimal('1000')
            for t in Transacao.objects.filter(usuario=outro)
        ))
