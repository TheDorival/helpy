from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    bio = models.TextField(blank=True, default='')
    telefone = models.CharField(max_length=20, blank=True, default='')
    data_nascimento = models.DateField(null=True, blank=True)
    avatar = models.ImageField(upload_to='avatares/', null=True, blank=True)

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def __str__(self):
        return self.get_full_name() or self.username
