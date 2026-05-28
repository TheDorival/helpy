from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

CATEGORIAS_PADRAO = [
    # (nome, tipo)
    ('Salário',              'receita'),
    ('Freelance',            'receita'),
    ('Investimentos',        'receita'),
    ('Outras receitas',      'receita'),

    ('Alimentação',          'despesa'),
    ('Moradia',              'despesa'),
    ('Transporte',           'despesa'),
    ('Saúde',                'despesa'),
    ('Educação',             'despesa'),
    ('Lazer',                'despesa'),
    ('Vestuário',            'despesa'),
    ('Contas e serviços',    'despesa'),
    ('Outras despesas',      'despesa'),
]


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_categorias_padrao(sender, instance, created, **kwargs):
    if not created:
        return
    from financeiro.models import Categoria
    Categoria.objects.bulk_create([
        Categoria(usuario=instance, nome=nome, tipo=tipo)
        for nome, tipo in CATEGORIAS_PADRAO
    ])
