from .base import *

DEBUG = False

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*'])

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
