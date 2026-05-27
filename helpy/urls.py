"""
URL configuration for helpy project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from helpy.views import home, painel
from usuarios.views import cadastro, configuracoes, perfil

urlpatterns = [
    path('', home, name='home'),
    path('entrar/', LoginView.as_view(template_name='login.html'), name='login'),
    path('sair/', LogoutView.as_view(), name='logout'),
    path('cadastro/', cadastro, name='cadastro'),
    path('painel/', painel, name='painel'),
    path('perfil/', perfil, name='perfil'),
    path('configuracoes/', configuracoes, name='configuracoes'),
    path('', include('financeiro.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
