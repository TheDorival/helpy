# Servidor próprio

Como sair do Render e rodar o Helpy na sua máquina Linux, acessível publicamente,
sem abrir nenhuma porta no roteador.

---

## O desenho

```
  internet
     │
     ▼
  Cloudflare  ──────  túnel (conexão de saída, iniciada de dentro)
                          │
  ┌───────────────────────┼─────────────────────────┐
  │  sua máquina          ▼                         │
  │                  ┌─────────┐                    │
  │                  │  tunel  │                    │
  │                  └────┬────┘                    │
  │                       │ rede interna do Docker  │
  │                  ┌────▼────┐      ┌──────────┐  │
  │                  │   web   │──────│    db    │  │
  │                  │gunicorn │      │ postgres │  │
  │                  └─────────┘      └────┬─────┘  │
  │                  127.0.0.1:8000        │        │
  │                                   volume + backup
  └─────────────────────────────────────────────────┘
```

O ponto central: **o roteador continua fechado**. O container do túnel abre uma
conexão de saída para a Cloudflare e o tráfego volta por ela. Não existe porta
aberta para escanear, não existe IP dinâmico para resolver, não existe
port forwarding para configurar errado.

---

## Antes de começar, três coisas honestas

**1. A Cloudflare enxerga o tráfego.** O TLS termina nos servidores dela, que
descriptografam, olham e recriptografam para o túnel. Para um app financeiro
isso é uma decisão, não um detalhe. As alternativas:

- aceitar (é o mesmo modelo de confiança de qualquer CDN, e você já confia no
  Render hoje, que também termina o TLS);
- porta 443 aberta com Let's Encrypt, e aí o TLS é ponta a ponta seu — em troca
  de IP dinâmico, firewall e a superfície de ataque que vem junto;
- não expor: só a sua rede privada via Tailscale, com TLS ponta a ponta e nada
  público.

**2. A disponibilidade passa a ser sua.** Queda de luz, queda de internet, um
`apt upgrade` que pede reboot — o app cai junto. O `restart: unless-stopped` do
compose faz os containers voltarem sozinhos quando a máquina liga, mas nada traz
a energia de volta.

**3. Os dados passam a ser seus.** No Neon, o backup é problema deles. Aqui é
seu. Você já viu o que acontece quando um banco some sem aviso — foi assim que
esta sessão começou. A seção de backup não é opcional.

---

## Distro

Você falou em Zorin por ser fácil de começar, e para **aprender Linux** é uma
boa escolha. Para servidor, o ideal seria Ubuntu Server LTS sem interface
gráfica — menos coisa instalada, menos coisa para atualizar, menos coisa que
pode ter vulnerabilidade.

Na prática, com o túnel, essa diferença encolhe bastante: nada da máquina fica
alcançável pela internet, só o container `web` é publicado, e mesmo assim só
para o `127.0.0.1`. **Zorin serve.** Use Zorin, aprenda Linux nele, e se um dia
o servidor virar coisa séria, reinstale como Ubuntu Server — a essa altura você
já vai saber fazer isso, e o compose sobe igual nos dois.

O que importa mais que a distro: ser uma base **LTS** e receber atualização de
segurança automática. Zorin 17/18 são baseados em Ubuntu LTS, então está ok.

---

## Passo a passo

### 1. Sistema base

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y curl git ufw
```

Atualização de segurança automática — a maior parte das invasões em servidor
caseiro é software desatualizado, não ataque sofisticado:

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 2. Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 100.64.0.0/10 to any port 22 proto tcp   # SSH só via Tailscale
sudo ufw enable
sudo ufw status verbose
```

Repare no que **não** está aqui: nenhuma regra para 80 ou 443. O túnel não
precisa de porta aberta. Se você não usa Tailscale, troque a regra do SSH pela
sua faixa de rede local (`192.168.0.0/16`) — mas nunca libere SSH para a
internet inteira.

### 3. SSH sem senha

Da sua máquina atual:

```bash
ssh-copy-id leonardo@ip-do-servidor
```

No servidor, edite `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

```bash
sudo systemctl restart ssh
```

> Teste a conexão por chave **numa segunda janela** antes de fechar a primeira.
> Errar isso e sair do terminal significa ir até a máquina com teclado e monitor.

### 4. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker            # ou saia e entre de novo
docker run --rm hello-world
```

### 5. O código

```bash
git clone https://github.com/<seu-usuario>/helpy.git ~/helpy
cd ~/helpy
cp deploy/env.example deploy/.env
chmod 600 deploy/.env
```

Gere uma chave nova — **não reaproveite a do Render**, ela já circulou:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Preencha `deploy/.env`: `SECRET_KEY`, `POSTGRES_PASSWORD` (use outra senha
aleatória), `DATABASE_URL` com essa mesma senha, `ALLOWED_HOSTS` e
`CSRF_TRUSTED_ORIGINS` com o seu domínio.

### 6. O túnel

No painel da Cloudflare: **Zero Trust → Networks → Tunnels → Create a tunnel**,
tipo *Cloudflared*. Copie o token que ele mostra para `TUNNEL_TOKEN` no
`deploy/.env`.

Ainda no painel, em **Public Hostnames**, adicione:

| campo    | valor                    |
|----------|--------------------------|
| Subdomain| `helpy`                  |
| Domain   | seu domínio              |
| Type     | `HTTP`                   |
| URL      | `web:8000`               |

`web:8000` é o nome do serviço na rede do compose — o túnel fala direto com o
container, sem passar pela máquina.

### 7. Subir

```bash
cd ~/helpy
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml logs -f web
```

Crie o seu usuário:

```bash
docker compose -f deploy/compose.yaml exec web python manage.py createsuperuser
```

---

## Trazer os dados do Neon

Você já tem o comando de backup do projeto, e ele foi feito exatamente para isso.

**Na origem** (sua máquina atual, apontando para o Neon):

```bash
python manage.py backup --usuario leonardo --saida ~/helpy-neon.json
```

**No servidor**, copie o arquivo e restaure:

```bash
scp ~/helpy-neon.json leonardo@servidor:~/
docker compose -f deploy/compose.yaml cp ~/helpy-neon.json web:/tmp/dados.json
docker compose -f deploy/compose.yaml exec web python manage.py backup --restaurar /tmp/dados.json
```

Confira o saldo no painel antes de desligar o Render. Se bater, você migrou.

> Só desative o serviço no Render **depois** de o servidor rodar alguns dias e
> de você ter restaurado um backup com sucesso pelo menos uma vez. Manter os
> dois no ar por uma semana não custa nada e evita arrependimento.

---

## Backup

Sem isso, todo o resto é enfeite.

```bash
mkdir -p ~/helpy/backups
deploy/backup.sh
```

O script gera o dump, **restaura num banco descartável para conferir que ele
volta**, conta as tabelas e as transações, e só então mantém o arquivo. Se a
verificação falhar, ele apaga o dump e sai com erro — você fica sabendo hoje, e
não no dia em que precisar.

Diário às 3h (`crontab -e`):

```
0 3 * * * cd /home/leonardo/helpy && deploy/backup.sh >> /var/log/helpy-backup.log 2>&1
```

**Tire uma cópia da máquina.** Backup no mesmo disco do banco não protege contra
o disco morrer:

```bash
DESTINO_REMOTO=leonardo@notebook:/backups/helpy/ deploy/backup.sh
```

Ou aponte para um HD externo montado, ou use `rclone` para nuvem. O importante é
que exista uma cópia em outro lugar físico.

### Restaurar

```bash
docker compose -f deploy/compose.yaml exec -T db \
    pg_restore -U helpy -d helpy --clean --if-exists < backups/helpy-2026-08-07_0300.dump
```

Faça isso uma vez, de propósito, com o servidor novo e sem dados importantes.
É a única forma de saber que funciona.

---

## Operação

```bash
cd ~/helpy
C="docker compose -f deploy/compose.yaml"

$C ps                    # o que está de pé
$C logs -f web           # acompanhar
$C restart web           # reiniciar só o app
$C exec db psql -U helpy # abrir o banco
```

**Atualizar depois de um push:**

```bash
git pull
$C up -d --build         # rebuild, migrate roda sozinho, web reinicia
$C logs --tail 50 web
```

**Espaço em disco** — a causa mais comum de servidor caseiro parar:

```bash
df -h
docker system prune -a   # remove imagens antigas
```

---

## Checklist de segurança

- [ ] `deploy/.env` com `chmod 600` e fora do Git
- [ ] `SECRET_KEY` nova, não a do Render
- [ ] `ALLOWED_HOSTS` com o domínio explícito, nunca `*`
- [ ] SSH por chave, sem senha, sem root
- [ ] `ufw` ativo, nada liberado para a internet
- [ ] `unattended-upgrades` ligado
- [ ] Banco sem porta publicada (confira: `docker compose ps` não deve mostrar
      `0.0.0.0:5432`)
- [ ] Backup rodando no cron **e** com cópia fora da máquina
- [ ] Uma restauração feita de verdade, ao menos uma vez
- [ ] `SECURE_HSTS_SECONDS` só subiu para 31536000 depois do HTTPS firme

Depois de tudo de pé:

```bash
docker compose -f deploy/compose.yaml exec web python manage.py check --deploy
```

---

## Quando der errado

**`CSRF verification failed` em todo formulário** — falta `CSRF_TRUSTED_ORIGINS`
com o esquema junto (`https://helpy.seudominio.com`, não só o domínio).

**Laço infinito de redirecionamento** — o proxy não está mandando
`X-Forwarded-Proto`. No túnel da Cloudflare o hostname público precisa apontar
para `HTTP` (não `HTTPS`) em `web:8000`.

**`DisallowedHost`** — o domínio não está em `ALLOWED_HOSTS`.

**`web` reiniciando em loop** — veja `logs migrate` primeiro; migration que falha
derruba tudo o que vem depois.

**Túnel conecta mas dá 502** — o `web` ainda não subiu ou morreu. `$C ps` e
`$C logs web`.
