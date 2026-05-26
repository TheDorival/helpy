from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Perfil', {
            'fields': ('bio', 'telefone', 'data_nascimento', 'avatar'),
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Perfil', {
            'fields': ('bio', 'telefone', 'data_nascimento', 'avatar'),
        }),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'telefone', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'telefone')
