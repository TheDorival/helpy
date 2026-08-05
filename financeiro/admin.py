from django.contrib import admin

from .models import Categoria, EventoVida, ImportacaoExtrato, RegraCategoria, Transacao


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'tipo', 'usuario')
    list_filter = ('tipo',)
    search_fields = ('nome',)


@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'tipo', 'valor', 'data', 'categoria', 'usuario')
    list_filter = ('tipo', 'data')
    search_fields = ('descricao',)
    date_hierarchy = 'data'


@admin.register(ImportacaoExtrato)
class ImportacaoExtratoAdmin(admin.ModelAdmin):
    list_display = ('arquivo_nome', 'formato', 'banco', 'n_importadas', 'n_ignoradas', 'criado_em', 'usuario')
    list_filter = ('formato',)


@admin.register(RegraCategoria)
class RegraCategoriaAdmin(admin.ModelAdmin):
    list_display = ('termo', 'categoria', 'aplica_a', 'ativa', 'usuario')
    list_filter = ('aplica_a', 'ativa')
    search_fields = ('termo',)


@admin.register(EventoVida)
class EventoVidaAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tipo', 'data', 'valor', 'destaque', 'usuario')
    list_filter = ('tipo', 'destaque')
    search_fields = ('titulo', 'descricao')
    date_hierarchy = 'data'
