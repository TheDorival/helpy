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

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def simbolo_moeda(self):
        return MOEDA_SIMBOLO.get(self.moeda, 'R$')
