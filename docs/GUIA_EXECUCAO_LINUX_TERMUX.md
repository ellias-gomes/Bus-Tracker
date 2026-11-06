# 📱 Guia de Execução Contínua: Termux (Android) & Linux

O **BusTracker** foi projetado para operar com consumo ultra-baixo de recursos (RAM < 80MB, uso desprezível de CPU), tornando-o ideal para rodar como um serviço autônomo 24/7 tanto em servidores Linux tradicionais quanto em **smartphones Android antigos** via Termux.

---

## 1. Executando em Segundo Plano no Termux (Android)

Transforme um celular antigo conectado ao Wi-Fi e ao carregador em um servidor doméstico completo para monitorar suas viagens.

### 1.1. Instalação do Termux e Pacotes Básicos
1. Instale o [Termux via F-Droid](https://f-droid.org/packages/com.termux/) (evite a versão defasada da Google Play Store).
2. Abra o Termux e execute:
   ```bash
   pkg update && pkg upgrade -y
   pkg install python git clang libxml2 libxslt -y
   ```

### 1.2. Impedir Suspensão de Energia do Android
Para que o Android não encerre o processo do Termux em segundo plano:
1. No Termux, execute:
   ```bash
   termux-wake-lock
   ```
2. Nas configurações do Android, vá em **Bateria / Otimização de Bateria** e marque o Termux como **"Sem restrições" / "Não otimizar"**.

### 1.3. Clonando o Projeto e Instalando
```bash
git clone https://github.com/seu-usuario/procura_onibus.git
cd procura_onibus

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.4. Configuração das Variáveis
```bash
cp .env.example .env
nano .env  # Preencha seu TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
```

### 1.5. Iniciando o Daemon
Para rodar continuamente com reconexão automática e log:
```bash
nohup python main.py --daemon > logs_daemon.log 2>&1 &
```
Para verificar se está rodando:
```bash
ps aux | grep python
tail -f logs_daemon.log
```

---

## 2. Executando no Linux (Pop!_OS / Ubuntu / Debian)

### 2.1. Opção A: Agendamento Diário via `cron`
Ideal se você usa o computador no dia a dia e prefere que o robô apenas acorde em horários fixos e encerre:

1. Abra a tabela cron do usuário:
   ```bash
   crontab -e
   ```
2. Adicione uma linha para executar todos os dias às 07:00 da manhã:
   ```bash
   0 7 * * * cd /caminho/completo/procura_onibus && /caminho/completo/procura_onibus/.venv/bin/python main.py --run-once >> /caminho/completo/procura_onibus/logs/cron.log 2>&1
   ```

### 2.2. Opção B: Serviço do Usuário via `systemd` (Daemon 24/7)
Ideal para manter o agendador e o Bot do Telegram respondendo a qualquer momento:

1. Crie o arquivo de serviço:
   ```bash
   mkdir -p ~/.config/systemd/user
   nano ~/.config/systemd/user/bustracker.service
   ```
2. Insira a configuração (ajuste os caminhos para o seu usuário):
   ```ini
   [Unit]
   Description=BusTracker Daemon & Telegram Bot
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/home/seu-usuario/procura_onibus
   ExecStart=/home/seu-usuario/procura_onibus/.venv/bin/python main.py --daemon
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=default.target
   ```
3. Ative e inicie o serviço:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now bustracker.service
   ```
4. Para ver os logs em tempo real:
   ```bash
   journalctl --user -u bustracker.service -f
   ```
