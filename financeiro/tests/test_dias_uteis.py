"""Contagem de dias úteis e calendário de feriados nacionais."""

from datetime import date

from django.test import SimpleTestCase

from financeiro.models import _nth_business_day, _pascoa, feriados_nacionais


class PascoaTests(SimpleTestCase):
    """Datas conhecidas do Domingo de Páscoa."""

    def test_datas_conhecidas(self):
        esperado = {
            2024: date(2024, 3, 31),
            2025: date(2025, 4, 20),
            2026: date(2026, 4, 5),
            2027: date(2027, 3, 28),
            2030: date(2030, 4, 21),
        }
        for ano, dia in esperado.items():
            with self.subTest(ano=ano):
                self.assertEqual(_pascoa(ano), dia)


class FeriadosTests(SimpleTestCase):

    def test_feriados_fixos_presentes(self):
        feriados = feriados_nacionais(2026)
        for mes, dia in ((1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)):
            with self.subTest(data=f'{dia:02d}/{mes:02d}'):
                self.assertIn(date(2026, mes, dia), feriados)

    def test_consciencia_negra_e_nacional(self):
        """Feriado nacional desde a Lei 14.759/2023."""
        self.assertIn(date(2026, 11, 20), feriados_nacionais(2026))

    def test_feriados_moveis(self):
        # Páscoa 2026: 05/04
        feriados = feriados_nacionais(2026)
        self.assertIn(date(2026, 2, 16), feriados)  # segunda de carnaval
        self.assertIn(date(2026, 2, 17), feriados)  # terça de carnaval
        self.assertIn(date(2026, 4, 3), feriados)   # sexta-feira santa
        self.assertIn(date(2026, 6, 4), feriados)   # corpus christi

    def test_domingo_de_pascoa_nao_entra(self):
        """A Páscoa cai no domingo e não é feriado civil listado."""
        self.assertNotIn(date(2026, 4, 5), feriados_nacionais(2026))


class DiaUtilTests(SimpleTestCase):
    """Novembro/2026 é o mês didático: 01 é domingo e 02 é Finados."""

    def test_novembro_2026_nas_tres_convencoes(self):
        casos = {
            'sem_feriados': date(2026, 11, 6),   # 2,3,4,5,6 (feriado conta)
            'com_feriados': date(2026, 11, 9),   # 3,4,5,6,9 (pula Finados)
            'clt':          date(2026, 11, 7),   # 3,4,5,6,7 (sábado conta)
        }
        for regra, esperado in casos.items():
            with self.subTest(regra=regra):
                self.assertEqual(_nth_business_day(2026, 11, 5, regra), esperado)

    def test_padrao_desconta_feriados(self):
        self.assertEqual(_nth_business_day(2026, 11, 5), date(2026, 11, 9))

    def test_primeiro_dia_util_pula_fim_de_semana(self):
        # 01/08/2026 é sábado
        self.assertEqual(_nth_business_day(2026, 8, 1), date(2026, 8, 3))

    def test_clt_aceita_sabado_mas_nao_domingo(self):
        self.assertEqual(_nth_business_day(2026, 8, 1, 'clt'), date(2026, 8, 1))
        # 02/08 é domingo: o 2º dia útil pela CLT é segunda
        self.assertEqual(_nth_business_day(2026, 8, 2, 'clt'), date(2026, 8, 3))

    def test_mes_que_comeca_com_feriado(self):
        # 01/01/2026 é feriado (quinta); primeiro dia útil é 02 (sexta)
        self.assertEqual(_nth_business_day(2026, 1, 1), date(2026, 1, 2))

    def test_n_maior_que_o_mes_retorna_none(self):
        self.assertIsNone(_nth_business_day(2026, 2, 40))

    def test_fevereiro_bissexto_com_carnaval_no_fim(self):
        """Fev/2028 tem 21 dias de semana, mas 28 e 29 são Carnaval.

        Sobram 19 dias úteis, terminando em 25/02 (sexta).
        """
        self.assertIn(date(2028, 2, 28), feriados_nacionais(2028))
        self.assertIn(date(2028, 2, 29), feriados_nacionais(2028))
        self.assertEqual(_nth_business_day(2028, 2, 19), date(2028, 2, 25))
        self.assertIsNone(_nth_business_day(2028, 2, 20))
