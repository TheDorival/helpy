from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MOEDA_CHOICES = [
    ('BRL', 'Real brasileiro (R$)'),
    ('USD', 'Dólar americano (US$)'),
    ('EUR', 'Euro (€)'),
    ('GBP', 'Libra esterlina (£)'),
]

MOEDA_SIMBOLO = {
    'BRL': 'R$',
    'USD': 'US$',
    'EUR': '€',
    'GBP': '£',
}


TEMA_CHOICES = [
    ('escuro',    'Black'),
    ('midnight',  'Midnight'),
    ('mint',      'Mint'),
    ('golden',    'Golden'),
    ('claro',     'Snowy'),
    ('contraste', 'Vault'),
]

ESCALA_FONTE_CHOICES = [
    (90,  'Pequena (90%)'),
    (100, 'Normal (100%)'),
    (110, 'Grande (110%)'),
    (125, 'Muito grande (125%)'),
]

COR_DESTAQUE_PADRAO = '#4c8eff'

REGRA_DIA_UTIL_CHOICES = [
    ('sem_feriados', 'Segunda a sexta, sem descontar feriados'),
    ('com_feriados', 'Segunda a sexta, descontando feriados nacionais'),
    ('clt',          'Sábado conta como dia útil (exclui domingos e feriados)'),
]


class Usuario(AbstractUser):
    bio = models.TextField(blank=True, default='')
    telefone = models.CharField(max_length=20, blank=True, default='')
    data_nascimento = models.DateField(null=True, blank=True)
    avatar = models.ImageField(upload_to='avatares/', null=True, blank=True)
    moeda = models.CharField(max_length=3, choices=MOEDA_CHOICES, default='BRL')
    dia_corte = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
    )
    regra_dia_util = models.CharField(
        max_length=12, choices=REGRA_DIA_UTIL_CHOICES, default='com_feriados',
    )
    tema = models.CharField(max_length=10, choices=TEMA_CHOICES, default='escuro')
    cor_destaque = models.CharField(max_length=7, default=COR_DESTAQUE_PADRAO)
    escala_fonte = models.PositiveSmallIntegerField(choices=ESCALA_FONTE_CHOICES, default=100)
    reduzir_animacoes = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def simbolo_moeda(self):
        return MOEDA_SIMBOLO.get(self.moeda, 'R$')

    @property
    def cor_destaque_personalizada(self):
        return bool(self.cor_destaque) and self.cor_destaque.lower() != COR_DESTAQUE_PADRAO

    @property
    def cor_destaque_rgb(self):
        """Hex '#rrggbb' → 'r g b' para uso em variável CSS com alpha."""
        h = (self.cor_destaque or COR_DESTAQUE_PADRAO).lstrip('#')
        try:
            return f'{int(h[0:2], 16)} {int(h[2:4], 16)} {int(h[4:6], 16)}'
        except (ValueError, IndexError):
            return '76 142 255'
