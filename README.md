# Flight Monitor ✈️

Monitor autônomo e contínuo (24/7) de tarifas de passagens aéreas (ida e volta ou só ida) via Google Flights, com persistência em SQLite e alertas instantâneos no Telegram.

Construído sob medida para rodar com consumo mínimo de recursos (CPU/RAM) em servidores domésticos (*self-hosted* / Linux *headless*).

---

## 🚀 Destaques da Arquitetura

- **Sem navegadores pesados:** Não utiliza Chromium, Selenium ou Playwright.
- **Impersonação TLS:** Utiliza `curl_cffi` para replicar perfeitamente a assinatura TLS de navegadores reais (JA3/JA4), contornando bloqueios de rede sem sobrecarga computacional.
- **Arquitetura em Camadas (Clean/Domain-Driven):**
  - `domain`: Entidades de dados puras e tipadas (`RouteConfig`, `FlightDeal`).
  - `clients`: Clientes de busca no Google Flights (`FlightSearchClient`) e de notificação (`TelegramNotifier`, `ConsoleNotifier`).
  - `storage`: Persistência local em SQLite (`FlightRepository`) com controle de menor preço histórico e política anti-spam (*cooldown*).
  - `services`: Orquestração de casos de uso (`MonitorService`).
  - `cli`: Interface de linha de comando ergonômica com Typer e Rich.
- **Gerenciamento com `uv`:** Resolução e instalação ultrarrápida de pacotes.

---

## 📁 Estrutura do Projeto

```
flight-monitor/
├── src/
│   └── flight_monitor/
│       ├── domain/            # Modelos de domínio (Pydantic)
│       │   └── models.py
│       ├── clients/           # Adapters de infraestrutura (Google Flights, Telegram)
│       │   ├── flights_client.py
│       │   └── notifier.py
│       ├── storage/           # Banco de dados SQLite
│       │   └── repository.py
│       ├── services/          # Orquestrador do monitor
│       │   └── monitor.py
│       ├── config.py          # Configurações tipadas (.env)
│       └── cli.py             # CLI do usuário (check, start, search, history)
├── tests/                     # Testes unitários com pytest
├── routes.json                # Lista de rotas ativas para monitorar
├── pyproject.toml             # Metadados e dependências (uv)
├── Makefile                   # Comandos rápidos de desenvolvimento
└── README.md
```

---

## 🛠️ Instalação e Configuração

### 1. Pré-requisitos
- Python `>= 3.12`
- Gerenciador de pacotes [`uv`](https://github.com/astral-sh/uv)

### 2. Configurar o ambiente
```bash
# Sincronizar dependências
uv sync

# Ou via Makefile
make setup
```

### 3. Configurar variáveis (.env)
Copie o exemplo e preencha suas credenciais do Telegram (opcional, para receber alertas no celular):
```bash
cp .env.example .env
```

```ini
TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
TELEGRAM_CHAT_ID="987654321"
CHECK_INTERVAL_MINUTES=60
NOTIFICATION_COOLDOWN_HOURS=12
```

> **Como pegar o Token e Chat ID do Telegram:**
> 1. Inicie uma conversa com `@BotFather` no Telegram e digite `/newbot` para criar seu bot e obter o `TELEGRAM_BOT_TOKEN`.
> 2. Mande uma mensagem para o bot criado e use `@userinfobot` para descobrir o seu `TELEGRAM_CHAT_ID`.

### 4. Configurar as Rotas (`routes.json`)
Edite o arquivo `routes.json` com as viagens que deseja acompanhar:
```json
[
  {
    "id": "gru-gig-novembro",
    "origin": "GRU",
    "destination": "GIG",
    "departure_date": "2026-11-10",
    "return_date": "2026-11-17",
    "target_price": 800.0,
    "currency": "BRL",
    "max_stops": "ANY",
    "cabin_class": "ECONOMY",
    "active": true
  }
]
```

---

## 💻 Como Usar (CLI)

### Fazer uma busca avulsa na hora
```bash
uv run flight-monitor search GRU MIA 2026-11-10 -r 2026-11-20 --currency BRL
```

### Rodar uma checagem única das rotas cadastradas
```bash
uv run flight-monitor check
# ou
make check
```

### Ver o histórico de preços já gravados
```bash
uv run flight-monitor history
# ou
make history
```

### Testar a notificação do Telegram
```bash
uv run flight-monitor test-alert
```

### Iniciar o monitor contínuo 24/7
```bash
uv run flight-monitor start
# ou
make start
```

---

## 🧪 Testes

Rode a suíte de testes unitários:
```bash
uv run pytest -v
# ou
make test
```

---

## 🐧 Rodando como Serviço no Linux (systemd)

Para rodar 24h em background no seu servidor (como o **talos**):

Crie `/etc/systemd/system/flight-monitor.service`:
```ini
[Unit]
Description=Flight Monitor 24/7 Service
After=network.target

[Service]
Type=simple
User=victor
WorkingDirectory=/home/victor/flight-monitor
ExecStart=/home/victor/.local/bin/uv run flight-monitor start
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Ative e inicie o serviço:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now flight-monitor
```
