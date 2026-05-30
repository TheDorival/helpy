from datetime import date

from django.core.management.base import BaseCommand

from financeiro.models import Transacao, TransacaoFixa, _avancar_data


class Command(BaseCommand):
    help = 'Apaga transações geradas para datas futuras e corrige ultima_geracao'

    def handle(self, *args, **options):
        hoje = date.today()

        # 1. Remove todas as transações com data futura
        futuras = Transacao.objects.filter(data__gt=hoje)
        total_apagadas = futuras.count()
        futuras.delete()
        self.stdout.write(f'Transações futuras removidas: {total_apagadas}')

        # 2. Recalcula ultima_geracao para cada TransacaoFixa
        for tf in TransacaoFixa.objects.all():
            ultima = self._ultima_ocorrencia(tf, hoje)
            TransacaoFixa.objects.filter(pk=tf.pk).update(ultima_geracao=ultima)
            self.stdout.write(
                f'  {tf} → ultima_geracao = {ultima}'
            )

        self.stdout.write(self.style.SUCCESS('Concluído.'))

    def _ultima_ocorrencia(self, tf, ate):
        """Retorna a última data <= ate que deveria ter sido gerada, ou None."""
        d = tf.data_inicio
        if d > ate:
            return None

        ultima = None
        while d <= ate:
            if tf.data_fim and d > tf.data_fim:
                break
            ultima = d
            d = _avancar_data(d, tf.frequencia, tf.intervalo_dias, tf.data_inicio.day)

        return ultima
