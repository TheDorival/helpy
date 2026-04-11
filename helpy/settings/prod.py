from .base import *

ALLOWED_HOSTS = ['seudominio.com', 'www.seudominio.com']

DATABASES['default']['CONN_MAX_AGE'] = 600  # connection pooling