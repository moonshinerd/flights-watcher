# Flights Watcher ✈️

> **Monitor autônomo e contínuo (24/7) de passagens aéreas via Google Flights com inteligência de tarifas, persistência SQLite e alertas instantâneos por E-mail (HTML) e Telegram.**

Construído sob medida para rodar com consumo mínimo de recursos (CPU e RAM) em servidores Linux modestos (*self-hosted*, netbooks headless, mini PCs ou Raspberry Pi).

---

## 🎯 Por que o Flights Watcher?

A maioria dos bots de passagens aéreas hoje depende de navegadores pesados (Selenium, Playwright, Chromium headless consumindo 400MB+ de RAM por consulta) ou APIs comerciais pagas que custam centenas de dólares por mês.

O **Flights Watcher** adota uma abordagem de engenharia reversa de alta performance:
1. **Zero Browser Overhead:** Não abre navegadores. As consultas são feitas via requisições HTTP diretas ao endpoint interno RPC do Google Flights.
2. **Evasão Anti-Bot via TLS Spoofing:** Emprega a biblioteca `curl_cffi` para impersonar a assinatura criptográfica TLS (JA3/JA4) de navegadores modernos (Chrome), contornando BotGuards sem exigir proxies residenciais rotativos caros para frequências de monitoramento razoáveis.
3. **Pegada de Memória Mínima:** Consome apenas **~35 MB de RAM** e responde em **1 a 2 segundos**, sendo ideal para hardware com recursos limitados (ex: processadores Intel Atom e 1-2 GB de RAM).
4. **Links Diretos para Compra:** Toda notificação traz um botão com link direto para o Google Flights já preenchido com a rota, passageiros e datas.
5. **Autoproteção com Alerta de Falhas:** Se o monitor enfrentar problemas de rede, bloqueios ou exceções contínuas, ele envia automaticamente um e-mail de alerta de erro para você intervir.

---

## 🏗️ Arquitetura do Software

O projeto segue os princípios de **Clean Architecture** e **Ports & Adapters (Hexagonal)**:

```
flights-watcher/
├── src/
│   └── flights_watcher/
│       ├── domain/            # Entidades puras e imutáveis (Pydantic v2)
│       │   └── models.py      # RouteConfig, FlightDeal
│       ├── clients/           # Adapters de infraestrutura externa
│       │   ├── flights_client.py  # Conexão com Google Flights (fli / curl_cffi)
│       │   └── notifier.py        # Notifiers: EmailNotifier, TelegramNotifier, ConsoleNotifier
│       ├── storage/           # Persistência de dados local
│       │   └── repository.py      # SQLite (price_history, notifications, anti-spam cooldown)
│       ├── services/          # Casos de uso e orquestração
│       │   └── monitor.py         # MonitorService (loop 24/7, cooldown, health & error alerts)
│       ├── config.py          # Configurações tipadas via pydantic-settings (.env)
│       └── cli.py             # CLI ergonômica com Typer e formatação Rich
├── tests/                     # Testes unitários com pytest e mocks
├── routes.json                # Matriz de rotas ativas sendo monitoradas
├── pyproject.toml             # Metadados e gerenciador uv
├── Makefile                   # Automação de tarefas de desenvolvimento
└── README.md
```

---

## 📬 Sistema de Notificações

### 1. E-mail (HTML Responsivo & Plain Text)
* Utiliza conexão segura via **Gmail SMTP SSL** (porta 465).
* **Alerta de Oportunidade:** Exibe card verde com destaque para o preço encontrado, meta estipulada, companhia aérea, escalas, horários de ida/volta e botão direto de compra no Google Flights.
* **Alerta de Erro:** Caso o monitor sofra falhas repetidas ou exceções não tratadas, envia um e-mail em tom de aviso com os detalhes do erro e o comando `ssh` para depuração no servidor.

### 2. Telegram Bot (Opcional)
* Envio via Telegram Bot API com formatação Markdown e link direto.
* Ativado automaticamente caso `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` estejam preenchidos no `.env`.

### 3. Política Anti-Spam (Cooldown Inteligente)
* O histórico de alertas é registrado no banco de dados SQLite (`flight_monitor.db`).
* Se uma passagem continuar abaixo da meta nas checagens seguintes, o alerta só é reenviado se:
  * O preço cair ainda mais (novo menor preço histórico); ou
  * Já tiver passado o tempo de *cooldown* configurado (padrão: 12 horas).

---

## 🚀 Instalação e Configuração

### 1. Pré-requisitos
* Python `>= 3.12`
* Gerenciador de pacotes [`uv`](https://github.com/astral-sh/uv)

Instalação do `uv` (caso ainda não tenha):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clonar e Instalar Dependências
```bash
git clone git@github.com:moonshinerd/flights-watcher.git
cd flights-watcher

# Sincroniza o ambiente virtual isolado (.venv)
uv sync
```

### 3. Configurar Credenciais (`.env`)
Copie o arquivo de exemplo:
```bash
cp .env.example .env
```

Edite o `.env`:
```ini
# Notificações por E-mail (Gmail SSL)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=seu-email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx   # Senha de Aplicativo do Gmail (16 dígitos)
ALERT_EMAIL_TO=seu-email@gmail.com

# Notificações pelo Telegram (Opcional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Parâmetros do Monitor
CHECK_INTERVAL_MINUTES=60           # Intervalo entre checagens no modo 24/7
NOTIFICATION_COOLDOWN_HOURS=12      # Horas para reenviar alerta para o mesmo preço
```

> **Como gerar uma Senha de App no Gmail:**
> 1. Acesse [Google Account Security](https://myaccount.google.com/security).
> 2. Certifique-se de que a **Verificação em duas etapas** está ativada.
> 3. Na barra de busca de configurações do Google, digite **"Senhas de app"**.
> 4. Crie uma nova chave (ex: nomeie como `flights-watcher`) e cole os 16 dígitos em `SMTP_PASSWORD`.

---

## ✈️ Configuração das Rotas (`routes.json`)

O arquivo [`routes.json`](routes.json) armazena a matriz de voos monitorados:

```json
[
  {
    "id": "bsb-cgh-03a06set27",
    "origin": "BSB",
    "destination": "CGH",
    "departure_date": "2027-09-03",
    "return_date": "2027-09-06",
    "target_price": 550.0,
    "currency": "BRL",
    "max_stops": "ANY",
    "cabin_class": "ECONOMY",
    "active": true
  }
]
```

### Dicionário de Campos:
| Campo | Tipo | Descrição |
| :--- | :--- | :--- |
| `id` | `string` | Identificador único da rota (usado no histórico do banco SQLite). |
| `origin` | `string` | Código IATA do aeroporto de origem (ex: `BSB`, `GRU`, `CGH`). |
| `destination` | `string` | Código IATA do aeroporto de destino. |
| `departure_date` | `string` | Data de ida no formato `YYYY-MM-DD`. |
| `return_date` | `string \| null` | Data de volta no formato `YYYY-MM-DD` (ou `null` para voo só de ida). |
| `target_price` | `float` | Preço teto desejado para disparar o alerta (em reais). |
| `currency` | `string` | Moeda da cotação (`BRL`, `USD`, `EUR`). Padrão: `BRL`. |
| `max_stops` | `string` | Filtro de escalas: `"0"` (direto), `"1"`, `"2+"` ou `"ANY"`. |
| `cabin_class` | `string` | `"ECONOMY"`, `"PREMIUM_ECONOMY"`, `"BUSINESS"` ou `"FIRST"`. |
| `active` | `bool` | Se `true`, a rota é verificada no ciclo 24/7; se `false`, é ignorada. |

---

## 💻 Interface de Linha de Comando (CLI)

O projeto expõe o binário `flights-watcher` gerenciado pelo `uv`:

### 1. Testar Envio de Alertas
Valide a integração de e-mail antes de ligar o serviço:
```bash
# Testar envio de passagem promocional fictícia por e-mail
uv run flights-watcher test-alert --channel email

# Testar alerta de ERRO/FALHA do sistema por e-mail
uv run flights-watcher test-alert --channel email --error
```

### 2. Checagem Única Imediata
Executa uma única rodada em todas as rotas ativas do `routes.json`:
```bash
uv run flights-watcher check
```

### 3. Busca Pontual Avulsa
Pesquise qualquer trecho na hora sem precisar editar o `routes.json`:
```bash
# Voo de ida e volta BSB -> CGH
uv run flights-watcher search BSB CGH 2027-06-08 -r 2027-06-11

# Voo só de ida com limite de escalas
uv run flights-watcher search GRU MIA 2026-11-10 --stops 0
```

### 4. Consultar Histórico de Preços
Exibe as últimas leituras gravadas no SQLite com formatação em tabela:
```bash
uv run flights-watcher history
```

### 5. Iniciar o Monitor Contínuo 24/7
Inicia o processo em primeiro plano (loop contínuo com sleep configurável):
```bash
uv run flights-watcher start
```

---

## 🐧 Instalação como Serviço no Linux (`systemd`)

Para manter o monitor rodando de forma ininterrupta, reiniciando sozinho após reboots ou falhas de energia:

### 1. Criar o arquivo de serviço
No seu servidor (ex: `talos`), crie o arquivo `/etc/systemd/system/flights-watcher.service`:

```ini
[Unit]
Description=Flights Watcher 24/7 Price Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=victor
WorkingDirectory=/home/victor/flights-watcher
ExecStart=/home/victor/.local/bin/uv run flights-watcher start
Restart=always
RestartSec=60
EnvironmentFile=/home/victor/flights-watcher/.env

# Limites de recursos (cortesia com servidor modesto)
Nice=10
MemoryMax=300M

[Install]
WantedBy=multi-user.target
```

### 2. Ativar e Iniciar o Serviço
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now flights-watcher.service
```

### 3. Comandos Úteis de Manutenção
```bash
# Ver status em tempo real
sudo systemctl status flights-watcher

# Ver logs das checagens
journalctl -u flights-watcher -f

# Ver últimas 50 linhas de log
journalctl -u flights-watcher -n 50 --no-pager

# Reiniciar o serviço
sudo systemctl restart flights-watcher
```

---

## 🧪 Suíte de Testes Unitários

Todos os componentes críticos (cálculo de datas, regras de notificação, banco SQLite, EmailNotifier e MonitorService) possuem cobertura de testes:

```bash
uv run pytest -v
```

---

## 📄 Licença

Distribuído sob a licença MIT. Desenvolvido para fins pessoais e educacionais de monitoramento automatizado de tarifas.
