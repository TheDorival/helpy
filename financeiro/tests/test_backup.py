"""Exportação e restauração dos dados do usuário."""

import json
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from financeiro.models import (AjusteSaldo, Categoria, CategoriaEssencial, Contrapartida,
                               Emprestimo, Entidade, Essencial, EventoVida, Meta,
                               ParcelaContrapartida, ParcelaEmprestimo, RegraCategoria,
                               SaldoExtra, Transacao, TransacaoFixa)

Usuario = get_user_model()


class BackupTests(TestCase):

    def setUp(self):
        self.u = Usuario.objects.create_user(username='dono', password='x')
        self.arquivo = Path(tempfile.gettempdir()) / 'helpy-teste-backup.json'
        if self.arquivo.exists():
            self.arquivo.unlink()
        self._povoar()

    def tearDown(self):
        if self.arquivo.exists():
            self.arquivo.unlink()

    def _povoar(self):
        # 'Moradia' já vem das categorias padrão criadas no cadastro
        self.cat = Categoria.objects.get(usuario=self.u, nome='Moradia', tipo='despesa')
        self.ent = Entidade.objects.create(usuario=self.u, nome='Imobiliária', tipo='empresa')
        self.tf = TransacaoFixa.objects.create(
            usuario=self.u, tipo='despesa', descricao='Aluguel', valor=Decimal('1200.50'),
            frequencia='mensal', data_inicio=date(2026, 1, 10), categoria=self.cat,
            entidade=self.ent, dia_util_n=5,
        )
        self.t = Transacao.objects.create(
            usuario=self.u, tipo='despesa', descricao='Aluguel de janeiro',
            valor=Decimal('1200.50'), data=date(2026, 1, 10),
            categoria=self.cat, entidade=self.ent, origem_fixa=self.tf,
        )
        cat_ess, _ = CategoriaEssencial.objects.get_or_create(
            slug='aluguel', defaults=dict(nome='Aluguel', tipo='despesa', icone='🏠'),
        )
        Essencial.objects.create(
            usuario=self.u, categoria=cat_ess, valor=Decimal('1200.50'),
            data_inicio=date(2026, 1, 10), transacao_fixa=self.tf, dia_vencimento=10,
        )
        emp = Emprestimo.objects.create(
            usuario=self.u, tipo='tomado', descricao='Carro',
            valor_total=Decimal('12000'), n_parcelas=2, data_inicio=date(2026, 2, 1),
        )
        emp.gerar_parcelas()
        Meta.objects.create(usuario=self.u, nome='Reserva', tipo='economia',
                            valor_alvo=Decimal('5000'), data_inicio=date(2026, 1, 1))
        SaldoExtra.objects.create(usuario=self.u, nome='Cripto', valor=Decimal('300'))
        AjusteSaldo.objects.create(usuario=self.u, data=date(2026, 1, 15),
                                   valor=Decimal('2500'), observacao='Saldo do extrato')
        EventoVida.objects.create(usuario=self.u, titulo='Mudança', tipo='moradia',
                                  data=date(2026, 1, 5), transacao=self.t)
        regra = RegraCategoria.objects.create(usuario=self.u, termo='ALUGUEL',
                                              categoria=self.cat, recorrente=self.tf,
                                              aplica_a='despesa')
        cp = Contrapartida.objects.create(
            usuario=self.u, origem=self.t, regra=regra, tipo='despesa',
            descricao='Pix crédito', valor_total=Decimal('1065.00'),
            taxa=Decimal('6.5'), categoria=self.cat,
        )
        cp.gerar_parcelas(date(2026, 3, 23), 3, 10)

    def _exportar(self):
        call_command('backup', usuario='dono', saida=str(self.arquivo), stdout=StringIO())
        return json.loads(self.arquivo.read_text(encoding='utf-8'))

    # ── exportação ────────────────────────────────────────────────────────────

    def test_exporta_todos_os_tipos(self):
        dados = self._exportar()
        registros = dados['registros']
        # o usuário nasce com as categorias padrão, então basta conter a nossa
        self.assertIn('Moradia', [c['nome'] for c in registros['categorias']])
        self.assertEqual(len(registros['transacoes']), 1)
        self.assertEqual(len(registros['recorrentes']), 1)
        self.assertEqual(len(registros['essenciais']), 1)
        self.assertEqual(len(registros['parcelas']), 2)
        self.assertEqual(len(registros['regras']), 1)
        self.assertEqual(len(registros['eventos_vida']), 1)

    def test_valores_monetarios_sem_perda(self):
        dados = self._exportar()
        self.assertEqual(dados['registros']['transacoes'][0]['valor'], '1200.50')

    def test_relacoes_viram_referencia_por_posicao(self):
        dados = self._exportar()
        transacao = dados['registros']['transacoes'][0]
        posicao_moradia = [c['nome'] for c in dados['registros']['categorias']].index('Moradia')
        self.assertEqual(transacao['categoria'], {'ref': posicao_moradia})
        self.assertEqual(transacao['origem_fixa'], {'ref': 0})
        self.assertEqual(transacao['entidade'], {'ref': 0})

    def test_catalogo_global_referenciado_por_slug(self):
        dados = self._exportar()
        self.assertEqual(dados['registros']['essenciais'][0]['categoria'], {'slug': 'aluguel'})

    def test_nao_exporta_dados_de_outro_usuario(self):
        outro = Usuario.objects.create_user(username='vizinho', password='x')
        Transacao.objects.create(usuario=outro, tipo='despesa', descricao='Alheia',
                                 valor=Decimal('10'), data=date(2026, 1, 1))
        dados = self._exportar()
        descricoes = [t['descricao'] for t in dados['registros']['transacoes']]
        self.assertNotIn('Alheia', descricoes)

    def test_usuario_inexistente(self):
        with self.assertRaises(CommandError):
            call_command('backup', usuario='fantasma', stdout=StringIO())

    def test_sem_argumentos(self):
        with self.assertRaises(CommandError):
            call_command('backup', stdout=StringIO())

    # ── restauração ───────────────────────────────────────────────────────────

    def test_restaura_apos_perda_total(self):
        self._exportar()
        # simula a perda do banco
        for modelo in (ParcelaContrapartida, Contrapartida, RegraCategoria, EventoVida,
                       AjusteSaldo, SaldoExtra, Meta, ParcelaEmprestimo, Emprestimo,
                       Essencial, Transacao, TransacaoFixa, Entidade, Categoria):
            if modelo in (ParcelaEmprestimo, ParcelaContrapartida):
                modelo.objects.all().delete()      # não têm campo `usuario`
            else:
                modelo.objects.filter(usuario=self.u).delete()
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 0)

        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())

        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 1)
        self.assertEqual(TransacaoFixa.objects.filter(usuario=self.u).count(), 1)
        ancora = AjusteSaldo.vigente(self.u)
        self.assertIsNotNone(ancora)
        self.assertEqual(ancora.valor, Decimal('2500.00'))
        self.assertEqual(ancora.data, date(2026, 1, 15))

        cp = Contrapartida.objects.get(usuario=self.u)
        self.assertEqual(cp.valor_total, Decimal('1065.00'))
        self.assertEqual(cp.parcelas.count(), 3)
        self.assertEqual(cp.origem, Transacao.objects.get(usuario=self.u))
        self.assertEqual(ParcelaEmprestimo.objects.filter(emprestimo__usuario=self.u).count(), 2)

    def test_restauracao_preserva_valores_e_datas(self):
        self._exportar()
        Transacao.objects.filter(usuario=self.u).delete()
        TransacaoFixa.objects.filter(usuario=self.u).delete()
        Categoria.objects.filter(usuario=self.u).delete()
        Entidade.objects.filter(usuario=self.u).delete()
        Essencial.objects.filter(usuario=self.u).delete()
        RegraCategoria.objects.filter(usuario=self.u).delete()
        EventoVida.objects.filter(usuario=self.u).delete()

        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())

        t = Transacao.objects.filter(usuario=self.u).first()
        self.assertEqual(t.valor, Decimal('1200.50'))
        self.assertEqual(t.data, date(2026, 1, 10))
        self.assertEqual(t.descricao, 'Aluguel de janeiro')

    def test_restauracao_refaz_os_vinculos(self):
        self._exportar()
        for modelo in (RegraCategoria, EventoVida, Essencial, Transacao,
                       TransacaoFixa, Entidade, Categoria):
            modelo.objects.filter(usuario=self.u).delete()

        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())

        t = Transacao.objects.filter(usuario=self.u).first()
        self.assertIsNotNone(t.categoria_id)
        self.assertEqual(t.categoria.nome, 'Moradia')
        self.assertIsNotNone(t.origem_fixa_id)
        self.assertEqual(t.origem_fixa.descricao, 'Aluguel')

        regra = RegraCategoria.objects.filter(usuario=self.u).first()
        self.assertEqual(regra.recorrente_id, t.origem_fixa_id)

        essencial = Essencial.objects.filter(usuario=self.u).first()
        self.assertEqual(essencial.categoria.slug, 'aluguel')
        self.assertEqual(essencial.transacao_fixa_id, t.origem_fixa_id)

    def test_restaurar_sem_substituir_soma_lancamentos(self):
        """Sem --substituir os lançamentos são somados aos existentes."""
        self._exportar()
        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())
        self.assertEqual(Transacao.objects.filter(usuario=self.u).count(), 2)

    def test_categorias_existentes_sao_reaproveitadas(self):
        """Restaurar não pode duplicar categoria de mesmo nome e tipo."""
        self._exportar()
        antes = Categoria.objects.filter(usuario=self.u).count()
        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())
        self.assertEqual(Categoria.objects.filter(usuario=self.u).count(), antes)

    def test_substituir_deixa_apenas_o_backup(self):
        self._exportar()
        Transacao.objects.create(usuario=self.u, tipo='despesa', descricao='Depois do backup',
                                 valor=Decimal('50'), data=date(2026, 3, 1))
        call_command('backup', restaurar=str(self.arquivo), substituir=True, stdout=StringIO())

        transacoes = Transacao.objects.filter(usuario=self.u)
        self.assertEqual(transacoes.count(), 1)
        self.assertEqual(transacoes.first().descricao, 'Aluguel de janeiro')

    def test_restaura_criando_usuario_ausente(self):
        self._exportar()
        Usuario.objects.filter(username='dono').delete()
        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())
        self.assertTrue(Usuario.objects.filter(username='dono').exists())
        self.assertEqual(Transacao.objects.filter(usuario__username='dono').count(), 1)

    def test_arquivo_inexistente(self):
        with self.assertRaises(CommandError):
            call_command('backup', restaurar='/tmp/nao-existe-helpy.json', stdout=StringIO())

    def test_versao_incompativel(self):
        self._exportar()
        dados = json.loads(self.arquivo.read_text(encoding='utf-8'))
        dados['versao'] = 99
        self.arquivo.write_text(json.dumps(dados), encoding='utf-8')
        with self.assertRaises(CommandError):
            call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())

    def test_preserva_data_de_criacao_original(self):
        """Restaurar não pode fazer todo registro parecer criado hoje."""
        criado_original = Transacao.objects.get(pk=self.t.pk).criado_em
        self._exportar()
        Transacao.objects.filter(usuario=self.u).delete()

        call_command('backup', restaurar=str(self.arquivo), stdout=StringIO())

        restaurada = Transacao.objects.filter(usuario=self.u).first()
        self.assertEqual(restaurada.criado_em, criado_original)

    def test_ciclo_completo_e_estavel(self):
        """Exportar → restaurar → exportar deve gerar o mesmo conteúdo."""
        primeiro = self._exportar()
        call_command('backup', restaurar=str(self.arquivo), substituir=True, stdout=StringIO())
        segundo = self._exportar()
        self.assertEqual(primeiro['registros'], segundo['registros'])
