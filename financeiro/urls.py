from django.urls import path

from . import views

urlpatterns = [
    path('receitas/', views.receitas, name='receitas'),
    path('receitas/nova/', views.nova_receita, name='nova_receita'),
    path('despesas/', views.despesas, name='despesas'),
    path('despesas/nova/', views.nova_despesa, name='nova_despesa'),
    path('transacao/<int:pk>/editar/', views.editar_transacao, name='editar_transacao'),
    path('transacao/<int:pk>/excluir/', views.excluir_transacao, name='excluir_transacao'),
    path('graficos/', views.graficos, name='graficos'),
    path('exportar/', views.exportar_dados, name='exportar_dados'),
]
