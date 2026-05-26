from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import CadastroForm, PerfilForm


def cadastro(request):
    if request.user.is_authenticated:
        return redirect('painel')

    form = CadastroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        usuario = form.save()
        login(request, usuario)
        return redirect('painel')

    return render(request, 'cadastro.html', {'form': form})


@login_required
def perfil(request):
    form = PerfilForm(
        request.POST or None,
        request.FILES or None,
        instance=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Perfil atualizado com sucesso.')
        return redirect('perfil')

    return render(request, 'usuarios/perfil.html', {'form': form})
