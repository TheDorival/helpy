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


# ── EXTRATO EM TEXTO / PDF (layout Caixa) ─────────────────────────────────────

# 02/02/2026 - 17:25:50 021725 COMPRA CARTAO DEBITO Favorecido 41,90 D 193,91 C
RE_LINHA_CAIXA = re.compile(
    r'^(?P<data>\d{2}/\d{2}/\d{4})'              # data
    r'(?:[\s\-–—]*\d{1,2}:\d{2}(?::\d{2})?)?'    # hora (traço e segundos opcionais)
    r'[\s\-–—]*(?P<doc>\d{4,8})?'                # nr. documento (opcional)
    r'\s*(?P<resto>\S.*)$'
)

# valor monetário com indicador D/C opcional (o OCR às vezes perde a letra)
RE_VALOR_DC = re.compile(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DC])?(?![\d,.])')

IGNORAR_HISTORICO = ('saldo dia', 'saldo anterior', 'saldo do dia', 'saldo bloqueado')

# Direção inferida pelo histórico quando o indicador D/C não é legível
PALAVRAS_DESPESA = ('enviado', 'compra', 'debito', 'débito', 'pagamento', 'saque',
                    'tarifa', 'saida', 'saída', 'transferencia enviada', 'boleto')
PALAVRAS_RECEITA = ('recebido', 'recebimento', 'deposito', 'depósito', 'credito',
                    'crédito', 'salario', 'salário', 'estorno', 'rendimento', 'entrada')


# Número colado ao indicador D/C sem a vírgula decimal: "81211C", "749 D", "1.01411C"
RE_SEM_VIRGULA = re.compile(
    r'(?<![\d,.])((?:\d{1,3}\.)*\d{3,})\s*([DC])(?![A-Za-zÀ-ÿ0-9])'
)


def _formatar_moeda(digitos):
    """'81211' → '812,11'; '223411' → '2.234,11'."""
    inteiro, centavos = digitos[:-2].lstrip('0') or '0', digitos[-2:]
    partes = []
    while len(inteiro) > 3:
        partes.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    partes.insert(0, inteiro)
    return '.'.join(partes) + ',' + centavos


def _reparar_numeros(texto):
    """Recupera valores em que o OCR perdeu a vírgula decimal.

    O reconhecimento no navegador às vezes lê "812,11 C" como "81211C". Como o
    indicador D/C marca o fim do número, dá para reinserir a vírgula com
    segurança nos dois últimos dígitos.
    """
    # vírgula seguida de barra: "2.259,/10" → "2.259,10"
    texto = re.sub(r',\s*/\s*(\d{2})(?!\d)', r',\1', texto)

    def _sub(m):
        return f'{_formatar_moeda(m.group(1).replace(".", ""))} {m.group(2)}'

    return RE_SEM_VIRGULA.sub(_sub, texto)


def _limpar_ocr(texto):
    """Corrige confusões comuns do OCR em textos do extrato."""
    t = texto.replace('R$', ' ').replace('RS ', ' ')
    t = re.sub(r'[|¦]', ' ', t)
    t = _reparar_numeros(t)
    return re.sub(r'\s{2,}', ' ', t).strip()


def _direcao_pelo_historico(texto):
    """Devolve 'D', 'C' ou '' inferindo pelo histórico do lançamento."""
    t = texto.lower()
    for p in PALAVRAS_RECEITA:
        if p in t:
            return 'C'
    for p in PALAVRAS_DESPESA:
        if p in t:
            return 'D'
    return ''


def _limpar_descricao(texto):
    """Remove CPF/CNPJ mascarados e ruído de OCR do fim da descrição."""
    # Tokens com asterisco e dígitos: ***.833.854***, **449.880/0"**, ***,105.468***
    tokens = []
    for tok in texto.split():
        if '*' in tok and any(c.isdigit() for c in tok):
            continue
        if re.fullmatch(r'[#"\'`~^|.,;:*\-–—]+', tok):
            continue
        tokens.append(tok)

    # Ruído do OCR sobre a máscara de CPF no fim da linha
    # (ex: "Hk B13.17 Geek", "DBAwKE", "rik", "*hk", "#*%")
    PALAVRAS_CURTAS_VALIDAS = {'dos', 'das', 'da', 'do', 'de', 'jr', 'me', 'ltd'}

    def _ruido(tok):
        limpo = tok.strip('*#%.,;:')
        if not limpo:
            return True
        if tok.lower() in PALAVRAS_CURTAS_VALIDAS:
            return False
        if re.search(r'\d', tok):
            return True
        if len(limpo) <= 2:
            return True
        # 3 letras sem cara de nome próprio (não começa com maiúscula seguida de minúsculas)
        if len(limpo) == 3 and not re.fullmatch(r'[A-ZÀ-Ý][a-zà-ÿ]{2}', limpo):
            return True
        # capitalização errática típica de OCR sobre asteriscos: DBAwKE, aBcD
        return bool(re.search(r'[a-z][A-Z]', limpo)) or (limpo[1:].isupper() and len(limpo) <= 4)

    while len(tokens) > 3 and _ruido(tokens[-1]):
        tokens.pop()

    return re.sub(r'\s{2,}', ' ', ' '.join(tokens)).strip()


def _juntar_quebradas(linhas):
    """O OCR às vezes joga os valores de uma linha para a linha seguinte.

    Quando uma linha começa com data mas não tem valor, e a próxima só tem
    valores/sobras, as duas são unidas.
    """
    saida = []
    i = 0
    limpas = [_limpar_ocr(l or '') for l in linhas]
    while i < len(limpas):
        atual = limpas[i]
        if (atual and RE_LINHA_CAIXA.match(atual) and not RE_VALOR_DC.search(atual)
                and i + 1 < len(limpas)):
            prox = limpas[i + 1]
            if prox and RE_VALOR_DC.search(prox) and not RE_LINHA_CAIXA.match(prox):
                saida.append(f'{atual} {prox}')
                i += 2
                continue
        saida.append(atual)
        i += 1
    return saida


def _validar_contra_saldos(registros):
    """Marca lançamentos cujo valor não bate com a variação da coluna Saldo.

    `registros` inclui também as linhas ignoradas (SALDO DIA), necessárias para
    a sequência de saldos ficar correta. O extrato lista do mais recente para o
    mais antigo, então: valor da linha = saldo dela − saldo da linha seguinte.
    """
    for i, r in enumerate(registros):
        item = r.get('item')
        if item is None or r['saldo'] is None:
            continue
        prox = registros[i + 1] if i + 1 < len(registros) else None
        if not prox or prox['saldo'] is None:
            continue
        esperado = r['saldo'] - prox['saldo']
        assinado = item['valor'] if item['tipo'] == 'receita' else -item['valor']
        item['validado'] = True
        if abs(esperado - assinado) > Decimal('0.02'):
            item['suspeito'] = True
            item['motivo_suspeita'] = f'Saldo do extrato indica {esperado:.2f}'


def parse_linhas_caixa(linhas):
    """Converte linhas de texto do 'Extrato por período' da Caixa em lançamentos.

    Aceita linhas vindas do PDF com texto ou do OCR feito no navegador.
    """
    registros = []
    lancamentos = []
    for linha in _juntar_quebradas(linhas):
        if not linha:
            continue

        m = RE_LINHA_CAIXA.match(linha)
        if not m:
            continue

        data = _data_csv(m.group('data'))
        if data is None:
            continue

        resto = m.group('resto')
        valores = RE_VALOR_DC.findall(resto)
        if not valores:
            continue

        # Saldo da linha (última coluna) — usado para conferência
        saldo = None
        if len(valores) >= 2 and valores[-1][1]:
            s = _valor_csv(valores[-1][0])
            if s is not None:
                saldo = s if valores[-1][1].upper() == 'C' else -s
        registro = {'saldo': saldo, 'item': None}
        registros.append(registro)

        # A última ocorrência é o saldo; a anterior é o valor do lançamento.
        # Quando só há uma, ela é o próprio valor.
        valor_txt, indicador = valores[-2] if len(valores) >= 2 else valores[0]
        valor = _valor_csv(valor_txt)
        if valor is None or valor == 0:
            continue

        direcao_hist = _direcao_pelo_historico(resto)

        if not indicador:
            indicador = direcao_hist
            if not indicador:
                continue  # sem como saber entrada ou saída — melhor não adivinhar

        # Linha com um único valor legível: pode ser o valor (saldo ilegível) ou o
        # próprio saldo (valor ilegível). Se o indicador contradiz o histórico,
        # provavelmente é o saldo — descartar em vez de inventar um lançamento.
        if len(valores) == 1 and direcao_hist and indicador != direcao_hist:
            continue

        # Descrição = tudo antes do primeiro valor monetário
        corte = RE_VALOR_DC.search(resto)
        descricao = resto[:corte.start()].strip(' -—') if corte else resto.strip()
        descricao = _limpar_descricao(descricao)

        if any(p in descricao.lower() for p in IGNORAR_HISTORICO):
            continue

        item = {
            'data': data,
            'valor': abs(valor),
            'tipo': 'receita' if indicador.upper() == 'C' else 'despesa',
            'descricao': (descricao or 'Lançamento')[:200],
            'fitid': '',
            'suspeito': False,
            'validado': False,
            'motivo_suspeita': '',
        }
        registro['item'] = item
        lancamentos.append(item)

    if not lancamentos:
        raise ExtratoInvalido(
            'Nenhum lançamento reconhecido. Confira se o arquivo é o "Extrato por período" da Caixa.'
        )

    _validar_contra_saldos(registros)
    lancamentos.sort(key=lambda x: x['data'])
    return lancamentos


def conferencia_lancamentos(lancamentos):
    """Resumo da checagem de cada lançamento contra a coluna Saldo do extrato.

    Conferir linha a linha é bem mais confiável que somar tudo, porque um único
    saldo mal lido não contamina o resultado inteiro.
    """
    total = len(lancamentos)
    divergem = sum(1 for l in lancamentos if l.get('suspeito'))
    conferem = sum(1 for l in lancamentos if l.get('validado') and not l.get('suspeito'))
    return {
        'total': total,
        'conferem': conferem,
        'divergem': divergem,
        'sem_conferencia': total - conferem - divergem,
        'ok': divergem == 0,
    }


def meta_do_extrato(linhas):
    """Extrai banco e conta do cabeçalho do extrato."""
    cabecalho = [_limpar_ocr(l or '') for l in linhas[:30]]
    conta = ''
    for l in cabecalho:
        if 'conta' in l.lower():
            m = re.search(r'(\d{3,4}\s*/\s*[\d.]+-?\d?)', l)
            if m:
                conta = m.group(1).replace(' ', '')
                break
    banco = 'Caixa Econômica Federal' if any('CAIXA' in l.upper() for l in cabecalho) else ''
    return {'banco': banco, 'conta': conta, 'periodo_inicio': None, 'periodo_fim': None}


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
