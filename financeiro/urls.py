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
    path('recorrentes/', views.fixas, name='fixas'),
    path('recorrentes/nova/', views.nova_fixa, name='nova_fixa'),
    path('recorrentes/<int:pk>/editar/', views.editar_fixa, name='editar_fixa'),
    path('recorrentes/<int:pk>/excluir/', views.excluir_fixa, name='excluir_fixa'),
    path('recorrentes/<int:pk>/toggle/', views.toggle_fixa, name='toggle_fixa'),
    path('exportar/', views.exportar_dados, name='exportar_dados'),
]
