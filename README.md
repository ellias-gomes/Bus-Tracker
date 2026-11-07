# 🚌 BusTracker: Monitor Inteligente e Preditor de Passagens Rodoviárias

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Pop!_OS%20%7C%20Termux%20(Android)-orange.svg)](#-executando-em-segundo-plano)
[![Tests](https://img.shields.io/badge/tests-30%20passed-brightgreen.svg)](tests/)

O **BusTracker** é um sistema autônomo, modular e de baixo consumo de recursos projetado para monitorar tarifas de passagens rodoviárias, identificar o **melhor momento de compra** com base em histórico e tendências, e alertar o usuário via **Telegram** sobre quedas de preço e escassez de assentos.

O sistema conta com **três modos de uso** pensados para cada ocasião (veja [docs/MODOS_DE_USO.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/MODOS_DE_USO.md)):
1. **🌐 Ambiente Gráfico no Navegador (`./bustracker gui`):** Painel visual completo com **Calendário Interativo mês a mês**, agendamento com 1 clique, busca visual de passagens, gráfico SVG de histórico e editor visual do `.env`/iCal.
2. **📱 Menu Interativo de Terminal — TUI (`./bustracker`):** Menu numerado passo a passo, ideal para **Termux (Android)** ou uso rápido no terminal sem precisar digitar comandos longos.
3. **⚡ Linha de Comando Direta — CLI (`./bustracker <comando>`):** Comandos diretos para scripts, `cron` e execução em segundo plano (`--daemon` / `--run-once`).

---

## 🎯 Principais Funcionalidades

- **Multi-Provedor & Agregação:**
  - Conector de alta performance para a **Buser** (extração direta via requisições HTTP leves no payload SSR Nuxt 3).
  - Conectores oficiais diretos para viações tradicionais: **Guanabara** (Guanabara, Util, Sampaio, Real Expresso via REST API Next.js), **Viação Cometa** (Grupo JCA - Cometa, 1001, Catarinense via REST API JCA) e **Viação Águia Branca** (via SAP Commerce Cloud).
  - Arquitetura extensível e preparada para novos conectores ([ClickBus](file:///home/elliasgomes/Documentos/procura_onibus/src/bustracker/providers/clickbus.py), [Pássaro Marron](file:///home/elliasgomes/Documentos/procura_onibus/src/bustracker/providers/passaro_marron.py)).
- **Roteamento Inteligente (Hubs & Proximidade):**
  - Caso sua cidade de destino não possua linha direta no horário pretendido, o sistema busca alternativas viáveis com desembarque em cidades vizinhas (hubs regionais com 0 a 1 baldeação ou conexão local estimada).
  - Consulte a documentação detalhada em [docs/ROTEAMENTO_E_HUBS.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/ROTEAMENTO_E_HUBS.md).
- **Algoritmo de "Melhor Momento de Compra":**
  - **Média Móvel e Histórico:** Identifica desvios de preço ($\mu$ e $\sigma$) em relação ao padrão histórico daquela rota.
  - **Gatilhos de Alvo (Target Price):** Notifica imediatamente quando o valor atinge patamares pré-configurados como excelentes ou justos.
  - **Urgência de Assentos:** Alerta se as vagas estiverem acabando rapidamente dentro da janela horária desejada (com filtro inteligente contra tetos artificiais de exibição).
  - Consulte a documentação completa em [docs/MOTOR_DE_DECISAO.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/MOTOR_DE_DECISAO.md).
- **Sincronização Flexível de Viagens:**
  - **Google Calendar / iCal:** Lê automaticamente eventos de uma URL `.ics`.
  - **Arquivo Local:** Edição simples em `data/viagens.json` ([data/viagens.example.json](file:///home/elliasgomes/Documentos/procura_onibus/data/viagens.example.json)).
  - **Telegram Bot Interativo:** Adicione novas datas, consulte status ou silencie passagens compradas pelo celular.
  - Consulte o guia completo do bot em [docs/TELEGRAM_BOT.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/TELEGRAM_BOT.md).
- **Filtros de Janela Horária e Segurança:**
  - Restrição de horários de embarque (ex: evitar embarques muito tarde da noite por motivos de segurança).
  - Horário limite de desembarque (ideal para quem viaja de madrugada e precisa chegar a tempo do trabalho ou compromissos).
  - Suporte completo a janelas que atravessam a meia-noite (ex: 22h às 02h).
- **Arquitetura Ultra-Leve:**
  - Desenvolvido em Python assíncrono com SQLite nativo (WAL mode).
  - Sem necessidade de Docker pesado ou navegadores com alto consumo de memória.
  - Perfeito para rodar 24/7 em desktops Linux ou em smartphones antigos com **Termux** ([docs/GUIA_EXECUCAO_LINUX_TERMUX.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/GUIA_EXECUCAO_LINUX_TERMUX.md)).

---

## 🏗️ Arquitetura do Sistema

```
                        +----------------------------+
                        |  Fontes de Agendamento     |
                        |  - Google Calendar (.ics)  |
                        |  - data/viagens.json       |
                        |  - Comandos Telegram       |
                        +----------------------------+
                                      |
                                      v
+-----------------------+   +--------------------+   +-----------------------+
|  Provedores Scraper   |-->|   Orquestrador     |<--|  Telegram Bot         |
|  - Buser              |   |     (Scheduler)    |   |  - Consultas `/status`|
|  - Guanabara / Sampaio|   +--------------------+   |  - Alertas Push       |
|  - Cometa (Grupo JCA) |             |              +-----------------------+
|  - Águia Branca       |             v              
|  - ClickBus / Outros  |    +------------------+    
+-----------------------+    |   Banco SQLite   |    
                             |  (Histórico &    |
                             |   Snapshots)     |
                             +------------------+
                                      |
                                      v
                             +------------------+
                             | Analisador de    |
                             | Decisão de Preço |
                             +------------------+
```

---

## 📚 Documentação Técnica Complementar

Para entender detalhes aprofundados sobre cada subsistema, consulte os guias na pasta `docs/`:
- [docs/MODOS_DE_USO.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/MODOS_DE_USO.md) — Guia visual do **Ambiente Gráfico (Web UI)**, **Menu Interativo (TUI)** e **CLI**.
- [docs/PROVEDORES.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/PROVEDORES.md) — Catálogo e arquitetura técnica dos conectores (Buser, Guanabara, Cometa, Águia Branca).
- [docs/MOTOR_DE_DECISAO.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/MOTOR_DE_DECISAO.md) — Fórmula estatística, regras de urgência e anti-spam.
- [docs/ROTEAMENTO_E_HUBS.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/ROTEAMENTO_E_HUBS.md) — Roteamento com baldeação e conexões locais estimadas.
- [docs/TELEGRAM_BOT.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/TELEGRAM_BOT.md) — Passo a passo para criar e interagir com o bot.
- [docs/GUIA_EXECUCAO_LINUX_TERMUX.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/GUIA_EXECUCAO_LINUX_TERMUX.md) — Como configurar o serviço 24/7 no Linux (`systemd`/`cron`) ou no Termux Android.

---

## 🚀 Como Começar

### 1. Pré-requisitos
- Python 3.10 ou superior
- `pip` e `git`

### 2. Instalação
Clone o repositório e configure o ambiente virtual:

```bash
git clone https://github.com/ellias-gomes/Bus-Tracker.git
cd Bus-Tracker

# Criação e ativação do ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalação das dependências
pip install -r requirements.txt
```

### 3. Configuração de Variáveis de Ambiente
Copie o arquivo de exemplo [.env.example](file:///home/elliasgomes/Documentos/procura_onibus/.env.example) para `.env`:

```bash
cp .env.example .env
```

Edite o arquivo `.env` com suas preferências:

```ini
# Configurações do Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321

# Rota Padrão e Janelas de Segurança
DEFAULT_ORIGIN=sao-paulo-sp
DEFAULT_DESTINATION=rio-de-janeiro-rj
DEFAULT_HUBS=

DEFAULT_OUTBOUND_DEPART_AFTER=18:00
DEFAULT_OUTBOUND_DEPART_BEFORE=22:00
DEFAULT_RETURN_DEPART_AFTER=20:00
DEFAULT_RETURN_ARRIVE_BEFORE=07:15

# Parâmetros de Preço Alvo (R$)
TARGET_PRICE_GOOD=80.00
TARGET_PRICE_EXCELLENT=60.00

# Conexão Local Estimada entre Hub e Destino (opcional: cidade-a|cidade-b|custo|minutos)
LOCAL_CONNECTIONS=campinas-sp|jundiai-sp|15.00|30;aparecida-sp|guaratingueta-sp|6.50|15
```

---

## ⚙️ Como Usar no Dia a Dia (3 Interfaces + Telegram + Calendário)

Você pode usar o atalho `./bustracker` (que já aciona o `.venv` automaticamente):

### Opção 1: 🌐 Ambiente Gráfico no Navegador (Web UI)
Ideal para pesquisar passagens, clicar nos dias de um **calendário visual mês a mês**, acompanhar gráficos de preço, ver o **Total Geral das Viagens** e baixar planilhas em CSV:
```bash
./bustracker gui
```
O navegador abrirá automaticamente em `http://127.0.0.1:8080`.

### Opção 2: 📱 Menu Interativo no Terminal (TUI Amigável para Termux / Linux)
Ideal para usar no celular via **Termux** ou no terminal sem precisar digitar comandos extensos. Basta rodar:
```bash
./bustracker
```
Um menu numerado (`[1]` a `[9]`, `[E]` para Exportar CSV) guiará você passo a passo (com cidades numeradas, datas curtas `DD/MM` e valores padrão preenchidos com `Enter`).

### Opção 3: ⚡ Linha de Comando Direta (CLI Tradicional)
```bash
# Busca avulsa em tempo real (aceita datas curtas DD/MM)
./bustracker search sao-paulo-sp rio-de-janeiro-rj 23/11 --before 22:00

# Cadastrar viagem manual ou a partir de um compromisso
./bustracker add 23/11 24/11 --name "Viagem Novembro"
./bustracker event 24/11 --name "Compromisso Presencial"

# Consultar status (com Combo Ida+Volta e Total Geral Estimado)
./bustracker status
./bustracker list
./bustracker history

# Exportar relatório financeiro em planilha CSV (padrão Brasil: ';' e ',')
./bustracker export -o data/relatorio_viagens.csv

# Marcar trecho como comprado (desconta do total a pagar e silencia alertas)
./bustracker bought <id_da_viagem> ida

# Executar ciclo único (cron) ou robô contínuo (daemon)
./bustracker --run-once
./bustracker --daemon
```

### Opção B: Pelo Bot do Telegram
Envie comandos interativos diretamente para o seu bot:
- `/adicionar 2026-11-23 2026-11-24 [destino-uf]` — Cadastra uma viagem (também aceita `/nova_viagem`).
- `/evento 2026-11-24 [nome]` — Cadastra ida (D-1) e volta (D0) a partir da data do compromisso.
- `/status` — Lista as viagens ativas e o menor preço encontrado nas últimas coletas.
- `/viagens` (ou `/listar`) — Lista todas as viagens monitoradas.
- `/historico [id] [ida|volta]` — Exibe gráfico de evolução de preços dos últimos 14 dias.
- `/buscar sao-paulo-sp rio-de-janeiro-rj 2026-11-23` — Realiza uma busca pontual em tempo real.
- `/verificar` — Dispara uma coleta imediata de todas as rotas.
- `/comprei <id> [ida|volta]` — Silencia alertas de um trecho já adquirido.
- `/remover <id>` — Desativa uma viagem monitorada.

### Opção C: Via Arquivo Local (`data/viagens.json`)
Crie ou edite o arquivo `data/viagens.json` baseado no [data/viagens.example.json](file:///home/elliasgomes/Documentos/procura_onibus/data/viagens.example.json):

```json
[
  {
    "id": "viagem-01",
    "origem": "São Paulo, SP",
    "destino": "Rio de Janeiro, RJ",
    "hub_alternativo": "",
    "data_ida": "2026-11-23",
    "data_volta": "2026-11-24",
    "limite_partida_ida": "22:00",
    "limite_chegada_volta": "07:15"
  }
]
```

### Opção D: Google Calendar / iCal
Adicione a URL do seu calendário no `.env` (`CALENDAR_ICS_URL`). O sistema filtra eventos com as palavras-chave definidas em `CALENDAR_KEYWORDS` e permite sobrescrever o destino na descrição do evento (ex.: `destino: sao-paulo-sp`).

---

## 📱 Executando em Segundo Plano

Consulte o passo a passo completo com arquivos de serviço prontos em [docs/GUIA_EXECUCAO_LINUX_TERMUX.md](file:///home/elliasgomes/Documentos/procura_onibus/docs/GUIA_EXECUCAO_LINUX_TERMUX.md):
- **Linux (`cron` ou `systemd`):** Monitoramento silencioso no desktop/notebook.
- **Android (via Termux):** Servidor autônomo 24/7 de baixíssimo consumo em aparelho celular antigo.

---

## 🧪 Testes Automatizados

O projeto conta com suíte de testes cobrindo todos os módulos críticos:
```bash
# Instalar dependências de desenvolvimento
pip install -r requirements-dev.txt

# Rodar os testes
pytest -v
```

---

## 📊 Estrutura de Notificação no Telegram

Quando o robô identifica uma oportunidade ou alteração relevante, ele envia uma mensagem formatada:

```text
🚨 OPORTUNIDADE DE PASSAGEM ENCONTRADA! 🚨

🟢 COMPRA RECOMENDADA
🧳 Viagem Novembro — IDA [cli-a1b2c3]
📍 São Paulo - SP → Rio de Janeiro - RJ
📅 23/11/2026 (Segunda) • faltam 18 dia(s)
⏰ Janela: saída 18:00–22:00

🚌 23/11 21:15 → 24/11 03:30 | R$ 59,90 | Buser (semi leito)
   📍 Embarque: Terminal Rodoviário Tietê (São Paulo)
   🏁 Desembarque: Terminal Rodoviário Novo Rio (Rio de Janeiro)
   🔁 Direto • total R$ 59,90
   💺 Vagas: 12+ • via buser

💡 Preço excelente (R$ 59,90) e bem abaixo da média histórica.
💡 25% abaixo da média de 14 dias (R$ 79,90).

[ Botão Inline: 🔗 Comprar na Buser ]
```

---

## 🔒 Segurança e Privacidade
- Informações sensíveis e tokens de API nunca são versionados (`.env` e bases SQLite protegidos pelo `.gitignore`).
- As consultas respeitam intervalo de requisição configurável (`REQUEST_DELAY_SECONDS`) para evitar bloqueios ou sobrecarga nos serviços consultados.

---

## 📝 Licença
Distribuído sob a licença MIT. Consulte `LICENSE` para mais detalhes.
