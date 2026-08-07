# Helpy — Gestão Financeira Pessoal

Aplicação web de finanças pessoais construída com Django. Pensada para uso individual, com foco em controle de receitas, despesas, recorrentes, empréstimos e metas financeiras.

---

## Funcionalidades

**Visão geral & Resumo**
- Dashboard com saldo em conta, previsão de gastos vs. média histórica e previsão de economias baseada em recorrentes
- Página de resumo mensal com gráficos de barras semanais e breakdown de despesas por categoria

**Essenciais**
- Catálogo pré-definido de 16 itens (Salário, Aluguel, Energia, Internet, etc.) agrupados por prioridade (Fundamental / Importante / Opcional)
- Cada item ativado gera automaticamente uma transação recorrente
- Suporte a salário fixo, comissão pura e fixo + comissão
- Pagamento mensal ou quinzenal, com dia fixo ou N-ésimo dia útil do mês
- Modal automático no dia de recebimento para registrar comissão

**Receitas & Despesas**
- Lançamento com categoria, entidade, valor e observação
- Modal de visualização detalhada em cada linha da tabela
- Exportação em CSV

**Recorrentes**
- Frequências: diária, semanal, quinzenal, mensal, bimestral, trimestral, semestral, anual ou intervalo customizado em dias
- Geração automática de transações ao acessar o sistema
- Toggle ativa/inativa por recorrente

**Empréstimos**
- Modo simples (sem juros) e completo (Tabela Price ou SAC)
- Personalização individual de vencimento e valor de cada parcela
- Acompanhamento de parcelas pagas com barra de progresso

**Metas**
- Tipos: Economia, Limite de gasto (por categoria) e Meta de receita
- Progresso automático calculado das transações do período
- Ajuste manual opcional
- Prazo opcional, com alertas de vencimento próximo
- Sugestões de metas baseadas nos gastos dos últimos 3 meses

**Saldo em conta**
- Saldo histórico acumulado (todas as receitas − despesas)
- Saldos extras inline: VA, criptomoedas, investimentos, outros
- Edição de valor diretamente no painel

---

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Django 6.0.4, Python 3.13 |
| Banco de dados | PostgreSQL (produção) / SQLite (dev) |
| ORM / migrations | Django ORM |
| Frontend | Tailwind CSS via CDN, vanilla JS |
| Gráficos | Chart.js 4 |
| Autenticação | Django auth + modelo de usuário customizado |
| Assets estáticos | WhiteNoise |
| Configuração | django-environ + `.env` |

---

## Pré-requisitos

- Python 3.11+
- PostgreSQL (opcional para dev — SQLite funciona por padrão)
- Git

---

## Instalação

```bash
git clone https://github.com/TheDorival/helpy.git
cd helpy

# Criar e ativar o ambiente virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS

# Instalar dependências
pip install -r requirements.txt
```

### Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env`:

```env
SECRET_KEY=sua-chave-secreta-aqui
DEBUG=True

# SQLite (desenvolvimento local)
DATABASE_URL=sqlite:///db.sqlite3

# PostgreSQL (produção ou banco remoto)
# DATABASE_URL=postgresql://usuario:senha@host:5432/helpy
```

### Aplicar migrations e rodar

```bash
python manage.py migrate
python manage.py createsuperuser   # opcional
python manage.py runserver
```

Acesse: [http://localhost:8000](http://localhost:8000)

---

## Estrutura do projeto

```
helpy/
├── helpy/                  # Configuração principal e views raiz
│   ├── settings/
│   │   ├── base.py         # Configurações comuns
│   │   ├── dev.py          # Ambiente de desenvolvimento
│   │   └── prod.py         # Ambiente de produção
│   ├── urls.py
│   └── views.py            # Dashboard e resumo mensal
│
├── financeiro/             # App principal de finanças
│   ├── models.py           # Transacao, TransacaoFixa, Emprestimo,
│   │                       # Meta, Essencial, SaldoExtra, ...
│   ├── views.py
│   └── urls.py
│
├── usuarios/               # Modelo de usuário customizado
│   └── models.py           # Usuario (AbstractUser + moeda, avatar...)
│
├── templates/              # Templates HTML (Django + Tailwind)
│   ├── base_painel.html    # Layout base com sidebar
│   ├── painel.html         # Dashboard (visão geral)
│   ├── resumo.html         # Resumo mensal com gráficos
│   └── financeiro/         # Templates de cada módulo
│
├── .env.example
├── manage.py
└── requirements.txt
```

---

## Testes

```bash
python manage.py test
```

A suíte roda em SQLite na memória, sem tocar o banco configurado no `.env` —
leva menos de um segundo e pode ser executada com o servidor no ar. Cobre
cálculo de dias úteis e feriados, geração e projeção de recorrentes, leitura de
extratos (OFX, CSV e PDF), conciliação com lançamentos importados, backup e
controle de acesso entre usuários.

O GitHub Actions executa a mesma suíte, mais `makemigrations --check` e
`check --deploy`, a cada push e pull request (`.github/workflows/ci.yml`).

---

## Backup e restauração

O banco de produção não guarda cópia dos seus dados por conta própria. O
comando abaixo gera um JSON independente do banco, que pode ser restaurado em
qualquer instalação do Helpy — inclusive de PostgreSQL para SQLite e vice-versa.

```bash
# exportar (gera helpy-backup-AAAA-MM-DD.json)
python manage.py backup --usuario leonardo

# escolher o destino
python manage.py backup --usuario leonardo --saida backups/2026-08.json

# restaurar somando aos dados existentes
python manage.py backup --restaurar backups/2026-08.json

# restaurar apagando antes o que existe hoje
python manage.py backup --restaurar backups/2026-08.json --substituir
```

O arquivo preserva valores, datas originais de criação e os vínculos entre
registros (transação → recorrente, essencial → recorrente, regra → categoria).
Categorias e entidades de mesmo nome são reaproveitadas em vez de duplicadas.

Para rodar contra o banco de produção a partir da sua máquina, aponte o
`DATABASE_URL` do `.env` para ele antes de executar o comando.

**Frequência sugerida:** uma exportação por mês, junto da importação do extrato,
guardada fora do computador (nuvem ou pendrive). O Neon mantém histórico próprio
de alguns dias, mas ele não substitui uma cópia sua — bancos gratuitos podem ser
suspensos ou removidos, como já aconteceu com o PostgreSQL do Render.

---

## Monitoramento de erros

Em produção, erros não tratados podem ser enviados ao [Sentry](https://sentry.io),
que avisa por e-mail com o traceback completo — sem isso, um erro 500 só aparece
se você for procurar nos logs do Render.

1. Crie uma conta gratuita e um projeto do tipo **Django**
2. Copie o DSN que aparece na tela (algo como `https://chave@o0.ingest.sentry.io/123`)
3. No Render, adicione a variável `SENTRY_DSN` com esse valor

Sem a variável definida, nada é enviado e a aplicação funciona normalmente —
inclusive no desenvolvimento local.

**Privacidade:** por ser um app financeiro, a integração remove do relatório o
corpo das requisições (valores e descrições de lançamentos), os cookies e os
cabeçalhos de autenticação. O que sobra é o suficiente para diagnosticar: URL,
método, navegador e o traceback. Há testes garantindo esse comportamento.

| Variável | Descrição | Padrão |
|---|---|---|
| `SENTRY_DSN` | Endereço do projeto no Sentry | vazio (desligado) |
| `SENTRY_ENVIRONMENT` | Nome do ambiente nos relatórios | `producao` |
| `SENTRY_TRACES_SAMPLE_RATE` | Amostragem de desempenho (0 a 1) | `0.0` |

---

## Servidor próprio

Para rodar o Helpy na sua própria máquina Linux, publicamente acessível e sem
abrir portas no roteador, veja [`deploy/README.md`](deploy/README.md) — inclui
Docker Compose com Postgres, túnel da Cloudflare, endurecimento do sistema,
backup verificado e a migração dos dados vindos do Render.

---

## Configuração de banco de dados remoto

Para usar PostgreSQL em outro computador via rede (ex: usando [Tailscale](https://tailscale.com)):

```env
DATABASE_URL=postgresql://helpy_user:senha@100.x.x.x:5432/helpy
```

O PostgreSQL do servidor precisa estar configurado para aceitar conexões da faixa de IPs do Tailscale (`100.64.0.0/10`) no `pg_hba.conf`, e `listen_addresses = '*'` no `postgresql.conf`.

---

## Variáveis de ambiente

| Variável | Descrição | Padrão |
|---|---|---|
| `SECRET_KEY` | Chave secreta do Django | — |
| `DEBUG` | Modo debug (`True`/`False`) | `False` |
| `DATABASE_URL` | URL de conexão com o banco | `sqlite:///db.sqlite3` |
| `ALLOWED_HOSTS` | Domínios aceitos em produção | `*` |
| `SECURE_HSTS_SECONDS` | Validade do HSTS em produção | `3600` |

Gere a `SECRET_KEY` com:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Use chaves diferentes em desenvolvimento e produção.

---

## Contribuindo

1. Fork o repositório
2. Crie uma branch: `git checkout -b feat/minha-feature`
3. Commit: `git commit -m 'feat: descrição da mudança'`
4. Push: `git push origin feat/minha-feature`
5. Abra um Pull Request

---

## Licença

MIT
