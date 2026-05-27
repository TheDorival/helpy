from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import AlterarSenhaForm, CadastroForm, ExcluirContaForm, PerfilForm, PreferenciasForm


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


@login_required
def configuracoes(request):
    senha_form = AlterarSenhaForm(user=request.user)
    preferencias_form = PreferenciasForm(instance=request.user)
    excluir_form = ExcluirContaForm(user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'alterar_senha':
            senha_form = AlterarSenhaForm(user=request.user, data=request.POST)
            if senha_form.is_valid():
                senha_form.save()
                update_session_auth_hash(request, senha_form.user)
                messages.success(request, 'Senha alterada com sucesso.')
                return redirect('configuracoes')

        elif action == 'preferencias':
            preferencias_form = PreferenciasForm(request.POST, instance=request.user)
            if preferencias_form.is_valid():
                preferencias_form.save()
                messages.success(request, 'Preferências salvas.')
                return redirect('configuracoes')

        elif action == 'excluir_conta':
            excluir_form = ExcluirContaForm(user=request.user, data=request.POST)
            if excluir_form.is_valid():
                request.user.delete()
                logout(request)
                return redirect('home')

    return render(request, 'usuarios/configuracoes.html', {
        'senha_form': senha_form,
        'preferencias_form': preferencias_form,
        'excluir_form': excluir_form,
    })
