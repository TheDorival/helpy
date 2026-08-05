"""Leitura de extratos bancários (OFX e CSV) para importação de transações.

Nada é gravado aqui: os parsers apenas devolvem listas de dicionários no formato
    {'data': date, 'valor': Decimal (sempre positivo), 'tipo': 'receita'|'despesa',
     'descricao': str, 'fitid': str}
A gravação acontece na view, após a revisão do usuário.
"""

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


class ExtratoInvalido(Exception):
    """Arquivo não pôde ser interpretado como extrato."""


# ── OFX ───────────────────────────────────────────────────────────────────────

def _decodificar(conteudo):
    """OFX brasileiro costuma vir em latin-1; tenta utf-8 primeiro."""
    if isinstance(conteudo, str):
        return conteudo
    for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
        try:
            return conteudo.decode(enc)
        except (UnicodeDecodeError, AttributeError):
            continue
    return conteudo.decode('latin-1', errors='replace')


def _tag(bloco, nome):
    """Extrai o valor de <NOME> — funciona em OFX SGML (sem fechamento) e XML."""
    m = re.search(rf'<{nome}>([^<\r\n]*)', bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ''


def _data_ofx(txt):
    """'20260731120000[-3:BRT]' ou '20260731' → date."""
    if not txt:
        return None
    limpo = re.sub(r'\[.*?\]', '', txt).strip()
    digitos = re.sub(r'\D', '', limpo)[:8]
    if len(digitos) < 8:
        return None
    try:
        return datetime.strptime(digitos, '%Y%m%d').date()
    except ValueError:
        return None


def _valor_ofx(txt):
    if not txt:
        return None
    t = txt.strip().replace(' ', '')
    # OFX usa ponto decimal, mas alguns bancos exportam com vírgula
    if ',' in t and '.' in t:
        t = t.replace('.', '').replace(',', '.')
    elif ',' in t:
        t = t.replace(',', '.')
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def parse_ofx(conteudo):
    """Lê um arquivo OFX e devolve (lancamentos, metadados)."""
    texto = _decodificar(conteudo)
    if '<STMTTRN' not in texto.upper():
        raise ExtratoInvalido(
            'Nenhum lançamento encontrado. Verifique se o arquivo é um OFX completo '
            '(a Caixa também gera uma versão resumida, que não contém os lançamentos).'
        )

    meta = {
        'banco': _tag(texto, 'ORG') or _tag(texto, 'BANKID'),
        'conta': _tag(texto, 'ACCTID'),
        'periodo_inicio': _data_ofx(_tag(texto, 'DTSTART')),
        'periodo_fim': _data_ofx(_tag(texto, 'DTEND')),
    }

    lancamentos = []
    for bloco in re.findall(r'<STMTTRN>(.*?)</STMTTRN>', texto, re.IGNORECASE | re.DOTALL):
        data = _data_ofx(_tag(bloco, 'DTPOSTED'))
        valor = _valor_ofx(_tag(bloco, 'TRNAMT'))
        if data is None or valor is None:
            continue

        memo = _tag(bloco, 'MEMO')
        name = _tag(bloco, 'NAME')
        descricao = (memo or name or _tag(bloco, 'TRNTYPE') or 'Lançamento').strip()
        if memo and name and name.lower() not in memo.lower():
            descricao = f'{name} — {memo}'

        lancamentos.append({
            'data': data,
            'valor': abs(valor),
            'tipo': 'receita' if valor >= 0 else 'despesa',
            'descricao': descricao[:200],
            'fitid': _tag(bloco, 'FITID')[:120],
        })

    if not lancamentos:
        raise ExtratoInvalido('O arquivo não contém lançamentos legíveis.')

    lancamentos.sort(key=lambda x: x['data'])
    if not meta['periodo_inicio']:
        meta['periodo_inicio'] = lancamentos[0]['data']
    if not meta['periodo_fim']:
        meta['periodo_fim'] = lancamentos[-1]['data']
    return lancamentos, meta


# ── CSV ───────────────────────────────────────────────────────────────────────

CABECALHOS_DATA = ('data', 'date', 'data lancamento', 'data movimento', 'dt')
CABECALHOS_VALOR = ('valor', 'value', 'amount', 'montante', 'vlr')
CABECALHOS_DESC = ('descricao', 'descrição', 'historico', 'histórico', 'memo',
                   'lancamento', 'lançamento', 'detalhe', 'description')
CABECALHOS_TIPO = ('tipo', 'type', 'natureza', 'd/c', 'debito/credito')


def _norm(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', (s or '').strip().lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def _data_csv(txt):
    txt = (txt or '').strip()
    for fmt in ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _valor_csv(txt):
    t = (txt or '').strip()
    if not t:
        return None
    negativo = t.startswith('-') or (t.startswith('(') and t.endswith(')'))
    t = re.sub(r'[^\d,.-]', '', t).lstrip('-')
    if ',' in t and '.' in t:
        t = t.replace('.', '').replace(',', '.')
    elif ',' in t:
        t = t.replace(',', '.')
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    return -v if negativo else v


def detectar_colunas(cabecalho):
    """Sugere os índices de data, valor, descrição e tipo a partir do cabeçalho."""
    sug = {'data': None, 'valor': None, 'descricao': None, 'tipo': None}
    for i, col in enumerate(cabecalho):
        c = _norm(col)
        if sug['data'] is None and any(c.startswith(k) for k in CABECALHOS_DATA):
            sug['data'] = i
        elif sug['valor'] is None and any(k in c for k in CABECALHOS_VALOR):
            sug['valor'] = i
        elif sug['descricao'] is None and any(k in c for k in CABECALHOS_DESC):
            sug['descricao'] = i
        elif sug['tipo'] is None and any(k == c for k in CABECALHOS_TIPO):
            sug['tipo'] = i
    return sug


def ler_csv(conteudo):
    """Devolve (cabecalho, linhas) já decodificado e com delimitador detectado."""
    texto = _decodificar(conteudo)
    amostra = texto[:4000]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=';,\t|')
        delim = dialeto.delimiter
    except csv.Error:
        delim = ';' if amostra.count(';') > amostra.count(',') else ','

    linhas = [l for l in csv.reader(io.StringIO(texto), delimiter=delim) if any(c.strip() for c in l)]
    if not linhas:
        raise ExtratoInvalido('O arquivo CSV está vazio.')

    # Descarta linhas iniciais menores que a maior linha (cabeçalhos de banco)
    largura = max(len(l) for l in linhas)
    linhas = [l for l in linhas if len(l) >= min(largura, 2)]
    if len(linhas) < 2:
        raise ExtratoInvalido('Não foi possível identificar colunas e dados no CSV.')

    return linhas[0], linhas[1:]


def parse_csv(linhas, col_data, col_valor, col_desc, col_tipo=None):
    """Converte as linhas do CSV em lançamentos, usando os índices informados."""
    lancamentos = []
    for linha in linhas:
        try:
            data = _data_csv(linha[col_data])
            valor = _valor_csv(linha[col_valor])
        except IndexError:
            continue
        if data is None or valor is None:
            continue

        descricao = ''
        if col_desc is not None and col_desc < len(linha):
            descricao = linha[col_desc].strip()

        tipo = 'receita' if valor >= 0 else 'despesa'
        if col_tipo is not None and col_tipo < len(linha):
            marca = _norm(linha[col_tipo])
            if marca.startswith('d') or 'debito' in marca or 'saida' in marca:
                tipo = 'despesa'
            elif marca.startswith('c') or 'credito' in marca or 'entrada' in marca:
                tipo = 'receita'

        lancamentos.append({
            'data': data,
            'valor': abs(valor),
            'tipo': tipo,
            'descricao': (descricao or 'Lançamento')[:200],
            'fitid': '',
        })

    if not lancamentos:
        raise ExtratoInvalido(
            'Nenhuma linha válida encontrada — confira se as colunas de data e valor estão corretas.'
        )
    lancamentos.sort(key=lambda x: x['data'])
    return lancamentos
