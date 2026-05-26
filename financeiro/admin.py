from django.contrib import admin

from .models import Categoria, Transacao


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
