#!/usr/bin/env bash
# Backup do Postgres do Helpy.
#
# Um backup que nunca foi restaurado não é um backup — é um arquivo. Por isso
# este script restaura o dump num banco descartável e confere se as tabelas
# vieram junto. Se a verificação falhar, o arquivo é descartado e o script sai
# com erro, para você descobrir hoje e não no dia em que precisar.
#
# Uso:
#   deploy/backup.sh                 # gera, verifica e rotaciona
#   DESTINO=/mnt/hd deploy/backup.sh # escolhe onde guardar
#
# Diário às 3h, via crontab do seu usuário (crontab -e):
#   0 3 * * * cd /home/leonardo/helpy && deploy/backup.sh >> /var/log/helpy-backup.log 2>&1

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f $RAIZ/deploy/compose.yaml"

DESTINO="${DESTINO:-$RAIZ/backups}"
MANTER_DIAS="${MANTER_DIAS:-30}"

# shellcheck disable=SC1091
set -a; source "$RAIZ/deploy/.env"; set +a
USUARIO="${POSTGRES_USER:-helpy}"
BANCO="${POSTGRES_DB:-helpy}"

mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

carimbo="$(date +%Y-%m-%d_%H%M)"
arquivo="$DESTINO/helpy-$carimbo.dump"

echo "[$(date +%H:%M:%S)] gerando $arquivo"

# -Fc: formato comprimido do próprio Postgres, restaurável com pg_restore e
# seletivo por tabela. Muito melhor que SQL puro quando dá problema.
$COMPOSE exec -T db pg_dump -U "$USUARIO" -d "$BANCO" -Fc > "$arquivo"
chmod 600 "$arquivo"

tamanho=$(stat -c%s "$arquivo")
if [ "$tamanho" -lt 1024 ]; then
    echo "ERRO: dump com $tamanho bytes — algo falhou" >&2
    rm -f "$arquivo"
    exit 1
fi

# ── Verificação: o dump volta mesmo? ──────────────────────────────────────────
echo "[$(date +%H:%M:%S)] verificando a restauração"

teste="verificacao_$carimbo"
limpar() { $COMPOSE exec -T db dropdb -U "$USUARIO" --if-exists "$teste" >/dev/null 2>&1 || true; }
trap limpar EXIT

$COMPOSE exec -T db createdb -U "$USUARIO" "$teste"
$COMPOSE exec -T db pg_restore -U "$USUARIO" -d "$teste" --no-owner < "$arquivo" >/dev/null

tabelas=$($COMPOSE exec -T db psql -U "$USUARIO" -d "$teste" -tAc \
    "select count(*) from information_schema.tables where table_schema='public'")
tabelas=$(echo "$tabelas" | tr -d '[:space:]')

if [ "${tabelas:-0}" -lt 10 ]; then
    echo "ERRO: restauração trouxe só $tabelas tabela(s) — backup inválido" >&2
    rm -f "$arquivo"
    exit 1
fi

transacoes=$($COMPOSE exec -T db psql -U "$USUARIO" -d "$teste" -tAc \
    "select count(*) from financeiro_transacao" | tr -d '[:space:]')

echo "[$(date +%H:%M:%S)] ok — $tabelas tabelas, $transacoes transações, $((tamanho / 1024)) KB"

# ── Rotação ───────────────────────────────────────────────────────────────────
find "$DESTINO" -name 'helpy-*.dump' -type f -mtime "+$MANTER_DIAS" -print -delete

# ── Cópia para fora da máquina ────────────────────────────────────────────────
# Backup que mora no mesmo disco do banco não protege contra o disco morrer.
# Descomente e ajuste um destes, ou faça o seu:
#
# rsync -a "$arquivo" outro-pc:/backups/helpy/
# rclone copy "$arquivo" drive:backups/helpy/
#
if [ -n "${DESTINO_REMOTO:-}" ]; then
    echo "[$(date +%H:%M:%S)] copiando para $DESTINO_REMOTO"
    rsync -a "$arquivo" "$DESTINO_REMOTO"
fi

echo "[$(date +%H:%M:%S)] concluído"
