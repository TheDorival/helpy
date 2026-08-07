# Imagem da aplicação. Multi-stage para não carregar compilador na imagem final.

# ── Etapa 1: dependências ─────────────────────────────────────────────────────
FROM python:3.13-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq-dev e gcc só existem aqui; a imagem final não os carrega
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/instalado -r requirements.txt


# ── Etapa 2: imagem final ─────────────────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=helpy.settings.prod

# libpq5 é a biblioteca de runtime do Postgres — sem os headers nem o compilador
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

# A aplicação nunca roda como root: se alguém escapar do processo, escapa para
# um usuário sem poder nenhum.
RUN useradd --create-home --shell /usr/sbin/nologin helpy

COPY --from=build /instalado /usr/local

WORKDIR /app
COPY --chown=helpy:helpy . .

# collectstatic no build: a imagem já sai pronta, sem escrever em disco na subida
RUN SECRET_KEY=build-apenas DATABASE_URL=sqlite:///tmp.db \
    python manage.py collectstatic --noinput \
 && rm -f tmp.db

USER helpy

EXPOSE 8000

# --access-logfile - manda o log para o stdout, onde o Docker o recolhe.
# 3 workers dá conta de sobra para uso pessoal e cabe em pouca RAM.
CMD ["gunicorn", "helpy.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
