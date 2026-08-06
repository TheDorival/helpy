"""Leitura de extratos: OFX, CSV e o 'Extrato por período' da Caixa."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from financeiro.importacao import (ExtratoInvalido, conferencia_lancamentos,
                                   detectar_colunas, ler_csv, meta_do_extrato,
                                   parse_csv, parse_linhas_caixa, parse_ofx)

OFX_CAIXA = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<SIGNONMSGSRSV1><SONRS>
<FI><ORG>CAIXA ECONOMICA FEDERAL<FID>104</FI>
</SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>BRL
<BANKACCTFROM><BANKID>104<ACCTID>000123456-7</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260701<DTEND>20260731
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260705120000[-3:BRT]<TRNAMT>3500.00<FITID>A1<MEMO>CREDITO SALARIO</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260706120000[-3:BRT]<TRNAMT>-89.90<FITID>A2<MEMO>COMPRA IFOOD</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260710<TRNAMT>-45,50<FITID>A3<NAME>ALUGUEL<MEMO>PAGAMENTO ALUGUEL</STMTTRN>
</BANKTRANLIST>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""


class OfxTests(SimpleTestCase):

    def test_le_lancamentos_e_metadados(self):
        lancamentos, meta = parse_ofx(OFX_CAIXA)
        self.assertEqual(len(lancamentos), 3)
        self.assertEqual(meta['banco'], 'CAIXA ECONOMICA FEDERAL')
        self.assertEqual(meta['conta'], '000123456-7')
        self.assertEqual(meta['periodo_inicio'], date(2026, 7, 1))

    def test_sinal_define_o_tipo(self):
        lancamentos, _ = parse_ofx(OFX_CAIXA)
        por_id = {l['fitid']: l for l in lancamentos}
        self.assertEqual(por_id['A1']['tipo'], 'receita')
        self.assertEqual(por_id['A2']['tipo'], 'despesa')
        self.assertEqual(por_id['A1']['valor'], Decimal('3500.00'))

    def test_aceita_virgula_decimal(self):
        por_id = {l['fitid']: l for l in parse_ofx(OFX_CAIXA)[0]}
        self.assertEqual(por_id['A3']['valor'], Decimal('45.50'))

    def test_combina_name_e_memo(self):
        por_id = {l['fitid']: l for l in parse_ofx(OFX_CAIXA)[0]}
        self.assertIn('ALUGUEL', por_id['A3']['descricao'])

    def test_data_com_fuso(self):
        por_id = {l['fitid']: l for l in parse_ofx(OFX_CAIXA)[0]}
        self.assertEqual(por_id['A1']['data'], date(2026, 7, 5))

    def test_encoding_latin1(self):
        conteudo = OFX_CAIXA.replace(b'CREDITO SALARIO', 'CRÉDITO SALÁRIO'.encode('latin-1'))
        lancamentos, _ = parse_ofx(conteudo)
        self.assertIn('CRÉDITO', lancamentos[0]['descricao'])

    def test_arquivo_sem_lancamentos_avisa_sobre_resumo(self):
        with self.assertRaises(ExtratoInvalido) as ctx:
            parse_ofx(b'<OFX></OFX>')
        self.assertIn('resumida', str(ctx.exception))


class CsvTests(SimpleTestCase):

    CSV = ('Data;Historico;Valor;Tipo\n'
           '05/07/2026;Salario;3500,00;C\n'
           '06/07/2026;Mercado;-250,75;D\n'
           'linha invalida\n'
           '10/07/2026;Farmacia;89,90;D\n')

    def test_detecta_delimitador_e_cabecalho(self):
        cabecalho, linhas = ler_csv(self.CSV.encode('utf-8'))
        self.assertEqual(cabecalho[0], 'Data')
        self.assertEqual(len(linhas), 3)

    def test_sugere_colunas_pelo_cabecalho(self):
        cabecalho, _ = ler_csv(self.CSV.encode('utf-8'))
        sugestao = detectar_colunas(cabecalho)
        self.assertEqual(sugestao['data'], 0)
        self.assertEqual(sugestao['valor'], 2)
        self.assertEqual(sugestao['descricao'], 1)

    def test_ignora_linhas_invalidas(self):
        _, linhas = ler_csv(self.CSV.encode('utf-8'))
        lancamentos = parse_csv(linhas, 0, 2, 1, 3)
        self.assertEqual(len(lancamentos), 3)

    def test_coluna_tipo_tem_prioridade_sobre_o_sinal(self):
        _, linhas = ler_csv(self.CSV.encode('utf-8'))
        lancamentos = parse_csv(linhas, 0, 2, 1, 3)
        farmacia = next(l for l in lancamentos if l['descricao'] == 'Farmacia')
        self.assertEqual(farmacia['tipo'], 'despesa')   # valor positivo, mas marcado D

    def test_sem_coluna_tipo_usa_o_sinal(self):
        _, linhas = ler_csv(self.CSV.encode('utf-8'))
        lancamentos = parse_csv(linhas, 0, 2, 1, None)
        farmacia = next(l for l in lancamentos if l['descricao'] == 'Farmacia')
        self.assertEqual(farmacia['tipo'], 'receita')

    def test_csv_sem_dados_validos(self):
        _, linhas = ler_csv('A;B\nx;y\n'.encode('utf-8'))
        with self.assertRaises(ExtratoInvalido):
            parse_csv(linhas, 0, 1, None, None)


class ExtratoCaixaTests(SimpleTestCase):
    """Linhas como saem do PDF (com ou sem OCR)."""

    LINHAS = [
        'CAIXA',
        'Conta 0055 / 1288.000797622325-0',
        'Lançamentos Nr. Doc Histórico/Complemento Favorecido Valor Saldo',
        '31/07/2026 - 00:00:00 000000 SALDO DIA 0,00 C 812,11 C',
        '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Débora Ewelyn Dos 202,00 D 812,11 C',
        '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul Sociedade de 570,00 D 1.014,11 C',
        '31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa Sorvetes 7,49 D 1.584,11 C',
    ]

    def test_le_lancamentos_ignorando_saldo_dia(self):
        lancamentos = parse_linhas_caixa(self.LINHAS)
        self.assertEqual(len(lancamentos), 3)
        self.assertNotIn('SALDO DIA', [l['descricao'] for l in lancamentos])

    def test_separa_operacao_do_favorecido(self):
        lancamentos = parse_linhas_caixa(self.LINHAS)
        boleto = next(l for l in lancamentos if l['valor'] == Decimal('570'))
        self.assertEqual(boleto['operacao'], 'PAGAMENTO DE BOLETO')
        self.assertEqual(boleto['descricao'], 'Seul Sociedade de')
        self.assertIn('PAGAMENTO DE BOLETO', boleto['texto_completo'])

    def test_indicador_dc_define_o_tipo(self):
        lancamentos = parse_linhas_caixa(self.LINHAS)
        self.assertTrue(all(l['tipo'] == 'despesa' for l in lancamentos))

    def test_extrai_conta_e_banco(self):
        meta = meta_do_extrato(self.LINHAS)
        self.assertEqual(meta['banco'], 'Caixa Econômica Federal')
        self.assertEqual(meta['conta'], '0055/1288.000797622325-0')

    # ── defeitos típicos de OCR ────────────────────────────────────────────

    def test_recupera_virgula_perdida_pelo_ocr(self):
        """'81211C' precisa virar 812,11 C."""
        linhas = ['31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 20200D 81211C']
        lancamentos = parse_linhas_caixa(linhas)
        self.assertEqual(lancamentos[0]['valor'], Decimal('202.00'))

    def test_valor_colado_ao_indicador(self):
        linhas = ['31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa 749D 2.23411C']
        self.assertEqual(parse_linhas_caixa(linhas)[0]['valor'], Decimal('7.49'))

    def test_hora_com_ponto_em_vez_de_dois_pontos(self):
        linhas = ['27/01/2026 - 11.37:28 271137 COMPRA CARTAO DEBITO Casa Vieira 20,88 D 58,28 C']
        lancamentos = parse_linhas_caixa(linhas)
        self.assertEqual(lancamentos[0]['data'], date(2026, 1, 27))
        self.assertEqual(lancamentos[0]['descricao'], 'Casa Vieira')

    def test_traco_ausente_entre_data_e_hora(self):
        linhas = ['02/02/2026 15:29:07 021529 PIX ENVIADO Roseli Feitosa 1.000,00 D 235,81 C']
        lancamentos = parse_linhas_caixa(linhas)
        self.assertEqual(lancamentos[0]['valor'], Decimal('1000.00'))

    def test_limpa_cpf_mascarado_da_descricao(self):
        linhas = ['31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Débora Ewelyn Dos ***.544.404*** 202,00 D 812,11 C']
        self.assertEqual(parse_linhas_caixa(linhas)[0]['descricao'], 'Débora Ewelyn Dos')

    def test_preserva_nome_de_estabelecimento_com_asterisco(self):
        linhas = ['30/07/2026 - 21:52:53 302152 COMPRA CARTAO DEBITO Mp*pizza 48,00 D 2.294,89 C']
        self.assertEqual(parse_linhas_caixa(linhas)[0]['descricao'], 'Mp*pizza')

    def test_direcao_pelo_historico_quando_falta_indicador(self):
        """Sem o D/C legível, o tipo vem do histórico."""
        linhas = ['30/07/2026 - 21:52:53 302152 COMPRA CARTAO DEBITO Loja 48,00 2.294,89 C']
        self.assertEqual(parse_linhas_caixa(linhas)[0]['tipo'], 'despesa')

    def test_linha_ambigua_e_descartada(self):
        """Valor ilegível e indicador contradizendo o histórico: melhor ignorar."""
        linhas = ['30/07/2026 - 21:52:53 302152 COMPRA CARTAO DEBITO Loja 2.294,89 C']
        with self.assertRaises(ExtratoInvalido):
            parse_linhas_caixa(linhas)

    def test_arquivo_sem_lancamentos(self):
        with self.assertRaises(ExtratoInvalido):
            parse_linhas_caixa(['texto qualquer', 'sem datas'])


class ConferenciaTests(SimpleTestCase):
    """Cada linha é checada contra a variação da coluna Saldo."""

    def test_marca_linha_que_nao_bate(self):
        """O valor do meio está errado: 1.014,11 − 1.584,11 = −570, não −999."""
        linhas = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 999,00 D 1.014,11 C',
            '31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa 7,49 D 1.584,11 C',
        ]
        lancamentos = parse_linhas_caixa(linhas)
        resumo = conferencia_lancamentos(lancamentos)
        self.assertEqual(resumo['divergem'], 1)
        self.assertFalse(resumo['ok'])

        suspeita = next(l for l in lancamentos if l['suspeito'])
        self.assertEqual(suspeita['valor'], Decimal('999.00'))

    def test_ultima_linha_fica_sem_conferencia(self):
        """Sem linha seguinte não há como validar pela variação do saldo."""
        linhas = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 570,00 D 1.014,11 C',
        ]
        resumo = conferencia_lancamentos(parse_linhas_caixa(linhas))
        self.assertEqual(resumo['conferem'], 1)
        self.assertEqual(resumo['sem_conferencia'], 1)

    def test_tudo_conferindo(self):
        linhas = [
            '31/07/2026 - 21:38:09 312138 DEB PIX CHAVE Debora 202,00 D 812,11 C',
            '31/07/2026 - 21:36:55 312136 PAGAMENTO DE BOLETO Seul 570,00 D 1.014,11 C',
            '31/07/2026 - 18:27:45 311827 COMPRA CARTAO DEBITO Illa 7,49 D 1.584,11 C',
        ]
        resumo = conferencia_lancamentos(parse_linhas_caixa(linhas))
        self.assertEqual(resumo['divergem'], 0)
        self.assertTrue(resumo['ok'])
