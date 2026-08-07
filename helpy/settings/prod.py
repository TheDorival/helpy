from .base import *

DEBUG = False

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

# Origens aceitas em requisições POST. Precisa do esquema junto do domínio
# ('https://helpy.exemplo.com'); sem isso, todo formulário atrás de um proxy
# HTTPS falha com "CSRF verification failed".
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# Quem termina o TLS é o proxy (Render, túnel da Cloudflare, nginx). Ele avisa
# o esquema original neste cabeçalho — sem isso o Django acha que a requisição
# chegou em HTTP e entra em laço de redirecionamento.
#
# Só é seguro porque nada além do proxy alcança a aplicação: no compose a porta
# fica presa em 127.0.0.1. Se um dia você expuser o gunicorn direto, qualquer um
# poderá forjar este cabeçalho e fingir que veio por HTTPS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS: o navegador passa a exigir HTTPS por conta própria, sem depender do
# redirecionamento. Começa em 1 hora; suba para 1 ano (31536000) depois de
# confirmar que tudo funciona só em HTTPS — o navegador guarda esse prazo e
# não há como voltar atrás antes de ele expirar.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False        # só ative com o domínio definitivo

# Entrar na lista de preload dos navegadores é praticamente irreversível e
# exige domínio próprio — decisão adiada de propósito, não esquecimento.
SILENCED_SYSTEM_CHECKS = ['security.W021']

# Cookies fora do alcance de JavaScript e não enviados em requisições de outros sites
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Evita que o navegador "adivinhe" o tipo do arquivo servido
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Sessão expira em 30 dias sem uso, renovando a cada acesso
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_SAVE_EVERY_REQUEST = True

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

DATABASES['default']['CONN_MAX_AGE'] = 600


# ── Monitoramento de erros (Sentry) ───────────────────────────────────────────
# Só liga se SENTRY_DSN estiver definido; sem a variável, nada é enviado e a
# aplicação segue normalmente.

SENTRY_DSN = env('SENTRY_DSN', default='')


def _limpar_dados_sensiveis(evento, dica=None):
    """Remove do relatório qualquer coisa que possa conter dado financeiro."""
    requisicao = evento.get('request') or {}
    requisicao.pop('data', None)      # corpo do POST (valores, descrições...)
    requisicao.pop('cookies', None)
    cabecalhos = requisicao.get('headers') or {}
    for campo in ('Cookie', 'Authorization'):
        cabecalhos.pop(campo, None)
    return evento


if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env('SENTRY_ENVIRONMENT', default='producao'),

        # Nunca anexar dados do usuário ao relatório: este é um app financeiro.
        # Sem isso, o Sentry mandaria e-mail, IP e corpo das requisições junto.
        send_default_pii=False,

        # Amostragem de desempenho — 0 desliga; suba se quiser medir lentidão
        traces_sample_rate=env.float('SENTRY_TRACES_SAMPLE_RATE', default=0.0),

        # Erros de 4xx (404, 403) não interessam; só falhas de verdade
        ignore_errors=[
            'django.http.Http404',
            'django.core.exceptions.PermissionDenied',
            'django.security.DisallowedHost',
        ],
        before_send=_limpar_dados_sensiveis,
    )
