"""Exporta e restaura os dados de um usuário em JSON.

Independente do banco: o arquivo gerado pode ser restaurado em qualquer
instalação do Helpy, seja Postgres ou SQLite.

    python manage.py backup --usuario leonardo
    python manage.py backup --usuario leonardo --saida backups/2026-08.json
    python manage.py backup --restaurar backups/2026-08.json
    python manage.py backup --restaurar backups/2026-08.json --substituir
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from financeiro.models import (AjusteSaldo, Categoria, CategoriaEssencial, Contrapartida,
                               Emprestimo, Entidade, Essencial, EventoVida, ImportacaoExtrato,
                               Meta, ParcelaContrapartida, ParcelaEmprestimo, RegraCategoria,
                               SaldoExtra, Transacao, TransacaoFixa)

Usuario = get_user_model()

VERSAO = 1

# Ordem importa na restauração: quem é referenciado vem primeiro.
MODELOS = [
    ('categorias',   Categoria),
    ('entidades',    Entidade),
    ('recorrentes',  TransacaoFixa),
    ('importacoes',  ImportacaoExtrato),
    ('transacoes',   Transacao),
    ('essenciais',   Essencial),
    ('emprestimos',  Emprestimo),
    ('parcelas',     ParcelaEmprestimo),
    ('metas',        Meta),
    ('saldos_extras', SaldoExtra),
    ('ajustes_saldo', AjusteSaldo),
    ('eventos_vida', EventoVida),
    ('regras',       RegraCategoria),
    # Depois das regras e das transações: a contrapartida referencia as duas
    ('contrapartidas', Contrapartida),
    ('parcelas_contrapartida', ParcelaContrapartida),
]

# Campos que apontam para outro registro exportado (viram referência por índice)
RELACOES = {
    'categoria', 'entidade', 'origem_fixa', 'importacao', 'transacao',
    'transacao_fixa', 'transacao_fixa_2', 'recorrente', 'emprestimo',
    'origem', 'regra', 'contrapartida', 'contrapartida_categoria',
}

# Modelos sem campo `usuario`: o dono vem pelo registro pai
DONO_INDIRETO = {
    ParcelaEmprestimo:     'emprestimo__usuario',
    ParcelaContrapartida:  'contrapartida__usuario',
}


def _do_usuario(modelo, usuario):
    """QuerySet dos registros que pertencem ao usuário, direta ou indiretamente."""
    return modelo.objects.filter(**{DONO_INDIRETO.get(modelo, 'usuario'): usuario})


def _serializar_valor(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


class Command(BaseCommand):
    help = 'Exporta ou restaura os dados financeiros de um usuário em JSON'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', help='Username a exportar')
        parser.add_argument('--saida', help='Arquivo de destino (padrão: helpy-backup-AAAA-MM-DD.json)')
        parser.add_argument('--restaurar', help='Arquivo JSON a restaurar')
        parser.add_argument('--substituir', action='store_true',
                            help='Apaga os dados atuais do usuário antes de restaurar')

    def handle(self, *args, **opcoes):
        if opcoes.get('restaurar'):
            return self._restaurar(opcoes['restaurar'], opcoes['substituir'])
        if opcoes.get('usuario'):
            return self._exportar(opcoes['usuario'], opcoes.get('saida'))
        raise CommandError('Informe --usuario para exportar ou --restaurar para importar.')

    # ── exportação ────────────────────────────────────────────────────────────

    def _exportar(self, username, saida):
        try:
            usuario = Usuario.objects.get(username=username)
        except Usuario.DoesNotExist:
            raise CommandError(f'Usuário "{username}" não encontrado.')

        dados = {
            'versao': VERSAO,
            'gerado_em': datetime.now().isoformat(timespec='seconds'),
            'usuario': username,
            'registros': {},
        }

        # pk original → posição na lista exportada
        indices = {}

        for chave, modelo in MODELOS:
            qs = _do_usuario(modelo, usuario).order_by('pk')

            linhas, indices[modelo] = [], {}
            for pos, obj in enumerate(qs):
                indices[modelo][obj.pk] = pos
                linhas.append(self._objeto_para_dict(obj, indices))
            dados['registros'][chave] = linhas

        caminho = Path(saida or f'helpy-backup-{date.today():%Y-%m-%d}.json')
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')

        total = sum(len(v) for v in dados['registros'].values())
        self.stdout.write(self.style.SUCCESS(f'{total} registro(s) exportado(s) para {caminho}'))
        for chave, linhas in dados['registros'].items():
            if linhas:
                self.stdout.write(f'  {chave}: {len(linhas)}')

    def _objeto_para_dict(self, obj, indices):
        saida = {}
        for campo in obj._meta.fields:
            nome = campo.name
            if nome in ('id', 'usuario'):
                continue

            if campo.is_relation:
                valor = getattr(obj, f'{nome}_id')
                if valor is None:
                    saida[nome] = None
                elif campo.related_model is CategoriaEssencial:
                    # catálogo global: referencia pelo slug, que é estável
                    saida[nome] = {'slug': getattr(obj, nome).slug}
                elif nome in RELACOES:
                    pos = indices.get(campo.related_model, {}).get(valor)
                    saida[nome] = {'ref': pos} if pos is not None else None
                else:
                    saida[nome] = None
            else:
                saida[nome] = _serializar_valor(getattr(obj, nome))
        return saida

    # ── restauração ───────────────────────────────────────────────────────────

    @transaction.atomic
    def _restaurar(self, arquivo, substituir):
        caminho = Path(arquivo)
        if not caminho.exists():
            raise CommandError(f'Arquivo não encontrado: {caminho}')

        dados = json.loads(caminho.read_text(encoding='utf-8'))
        if dados.get('versao') != VERSAO:
            raise CommandError(f'Backup na versão {dados.get("versao")}, esperado {VERSAO}.')

        username = dados['usuario']
        usuario, criado = Usuario.objects.get_or_create(username=username)
        if criado:
            usuario.set_unusable_password()
            usuario.save()
            self.stdout.write(self.style.WARNING(
                f'Usuário "{username}" criado sem senha — defina uma com changepassword.'
            ))

        if substituir:
            for _, modelo in reversed(MODELOS):
                _do_usuario(modelo, usuario).delete()
            self.stdout.write('Dados anteriores removidos.')

        criados = {}   # modelo → lista de objetos na ordem do backup
        total = reaproveitados = 0

        for chave, modelo in MODELOS:
            criados[modelo] = []
            for linha in dados['registros'].get(chave, []):
                obj = self._dict_para_objeto(modelo, linha, usuario, criados)

                # Categoria e Entidade têm chave natural (nome + tipo): se já
                # existirem, reaproveita em vez de duplicar — é o que acontece
                # ao restaurar sobre um usuário novo, que já nasce com as
                # categorias padrão.
                existente = self._buscar_equivalente(modelo, obj, usuario)
                if existente is not None:
                    criados[modelo].append(existente)
                    reaproveitados += 1
                    continue

                obj.save()
                self._preservar_datas_automaticas(modelo, obj, linha)
                criados[modelo].append(obj)
                total += 1

        if reaproveitados:
            self.stdout.write(f'{reaproveitados} registro(s) já existentes reaproveitados.')

        self.stdout.write(self.style.SUCCESS(
            f'{total} registro(s) restaurado(s) para "{username}".'
        ))

    # Modelos com chave natural própria — restaurar não deve duplicá-los
    CHAVES_NATURAIS = {
        Categoria: ('nome', 'tipo'),
        Entidade: ('nome', 'tipo'),
        Essencial: ('categoria_id',),
    }

    def _preservar_datas_automaticas(self, modelo, obj, linha):
        """Devolve o `criado_em` original.

        Campos com auto_now_add/auto_now são reescritos pelo Django no save,
        o que faria todo registro restaurado parecer criado hoje.
        """
        forcar = {}
        for campo in modelo._meta.fields:
            automatico = getattr(campo, 'auto_now_add', False) or getattr(campo, 'auto_now', False)
            if automatico and linha.get(campo.name):
                forcar[campo.name] = self._valor_para_campo(campo, linha[campo.name])
        if forcar:
            modelo.objects.filter(pk=obj.pk).update(**forcar)
            for nome, valor in forcar.items():
                setattr(obj, nome, valor)

    def _buscar_equivalente(self, modelo, obj, usuario):
        campos = self.CHAVES_NATURAIS.get(modelo)
        if not campos:
            return None
        filtro = {campo: getattr(obj, campo) for campo in campos}
        return modelo.objects.filter(usuario=usuario, **filtro).first()

    def _dict_para_objeto(self, modelo, linha, usuario, criados):
        campos = {}
        for campo in modelo._meta.fields:
            nome = campo.name
            if nome in ('id', 'usuario'):
                continue
            valor = linha.get(nome)

            if campo.is_relation:
                if not valor:
                    campos[f'{nome}_id'] = None
                elif 'slug' in valor:
                    alvo = CategoriaEssencial.objects.filter(slug=valor['slug']).first()
                    campos[f'{nome}_id'] = alvo.pk if alvo else None
                else:
                    lista = criados.get(campo.related_model, [])
                    pos = valor.get('ref')
                    campos[f'{nome}_id'] = lista[pos].pk if pos is not None and pos < len(lista) else None
            elif valor is None:
                campos[nome] = None
            else:
                campos[nome] = self._valor_para_campo(campo, valor)

        if modelo not in DONO_INDIRETO:
            campos['usuario'] = usuario
        return modelo(**campos)

    def _valor_para_campo(self, campo, valor):
        tipo = campo.get_internal_type()
        if tipo == 'DecimalField':
            return Decimal(valor)
        if tipo == 'DateField':
            return datetime.fromisoformat(valor).date()
        if tipo == 'DateTimeField':
            return datetime.fromisoformat(valor)
        return valor
