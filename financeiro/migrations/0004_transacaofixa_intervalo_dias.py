from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0003_alter_transacao_descricao_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transacaofixa',
            name='intervalo_dias',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='transacaofixa',
            name='frequencia',
            field=models.CharField(
                choices=[
                    ('diaria', 'Diária'),
                    ('semanal', 'Semanal'),
                    ('quinzenal', 'Quinzenal'),
                    ('mensal', 'Mensal'),
                    ('bimestral', 'Bimestral'),
                    ('trimestral', 'Trimestral'),
                    ('semestral', 'Semestral'),
                    ('anual', 'Anual'),
                    ('intervalo', 'A cada N dias'),
                ],
                default='mensal',
                max_length=20,
            ),
        ),
    ]
