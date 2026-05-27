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
    path('categorias/', views.categorias, name='categorias'),
    path('categorias/nova/', views.nova_categoria, name='nova_categoria'),
    path('categorias/<int:pk>/editar/', views.editar_categoria, name='editar_categoria'),
    path('categorias/<int:pk>/excluir/', views.excluir_categoria, name='excluir_categoria'),
    path('entidades/', views.entidades, name='entidades'),
    path('entidades/nova/', views.nova_entidade, name='nova_entidade'),
    path('entidades/<int:pk>/editar/', views.editar_entidade, name='editar_entidade'),
    path('entidades/<int:pk>/excluir/', views.excluir_entidade, name='excluir_entidade'),
    path('exportar/', views.exportar_dados, name='exportar_dados'),
]
