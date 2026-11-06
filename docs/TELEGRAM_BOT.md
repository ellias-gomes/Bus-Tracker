# 🤖 Guia de Configuração e Uso do Telegram Bot

O **BusTracker** conta com um bot integrado que executa duas funções vitais:
1. **Alertas Proativos (Push):** Notifica no seu chat privado sempre que uma passagem atinge o melhor momento de compra ou as vagas estiverem acabando.
2. **Interface Interativa:** Permite cadastrar viagens, consultar preços em tempo real e silenciar alertas de bilhetes já comprados diretamente pelo celular.

---

## 1. Criando o seu Bot no Telegram

1. No aplicativo do Telegram, procure pelo usuário oficial `@BotFather`.
2. Envie o comando `/newbot`.
3. Escolha um nome de exibição (ex: `Meu Monitor de Ônibus`) e um username único terminado em `bot` (ex: `meu_onibus_monitor_bot`).
4. O BotFather fornecerá um **Token de Acesso HTTP API** (ex: `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`).
5. Copie esse token e coloque na variável `TELEGRAM_BOT_TOKEN` do seu arquivo `.env`.

---

## 2. Descobrindo o seu `TELEGRAM_CHAT_ID`

Por segurança, o BusTracker **ignora mensagens de qualquer usuário desconhecido** e só se comunica com o seu ID autorizado:

1. No Telegram, procure pelo bot `@userinfobot`.
2. Envie qualquer mensagem ou dê `/start`.
3. O bot responderá com o seu **Id numérico** (ex: `987654321`).
4. Copie esse número e coloque na variável `TELEGRAM_CHAT_ID` do `.env`.
5. Abra o chat do bot que você acabou de criar no passo 1 e clique em **Começar** (`/start`).

---

## 3. Lista de Comandos Suportados

| Comando | Descrição | Exemplo |
| :--- | :--- | :--- |
| `/status` | Exibe o resumo de todas as viagens e detalhes do próximo trecho | `/status` |
| `/viagens` ou `/listar` | Lista todas as viagens cadastradas e seus horários | `/viagens` |
| `/adicionar` | Cadastra uma nova viagem informando as datas | `/adicionar 2026-11-23 2026-11-24` |
| `/evento` | Cria viagem calculando ida D-1 e volta D0 a partir do evento | `/evento 2026-11-24 Prova Bimestral` |
| `/buscar` | Faz uma consulta em tempo real nos provedores | `/buscar rio-de-janeiro-rj sao-paulo-sp 2026-11-23` |
| `/historico` | Exibe o gráfico ASCII com a oscilação de tarifas dos últimos 14 dias | `/historico t1 ida` |
| `/verificar` | Força uma varredura imediata de todas as rotas | `/verificar` |
| `/comprei` | Marca a viagem como comprada e silencia notificações | `/comprei t1 ida` |
| `/remover` | Desativa uma viagem cadastrada | `/remover t1` |
| `/ajuda` | Mostra as instruções e sintaxe dos comandos | `/ajuda` |

---

## 4. Anatomia de uma Mensagem de Alerta

Quando o robô encontra uma boa oportunidade, a mensagem enviada contém:
- **Nível da Decisão:** (Ex: `🟢 COMPRA RECOMENDADA` ou `🔴 ÚLTIMAS VAGAS`).
- **Resumo do Trecho:** Horários de partida e chegada, empresa operadora, tipo de assento e pontos de embarque/desembarque.
- **Vagas Restantes:** Identificação da disponibilidade real de assentos.
- **Preço vs. Média Histórica:** Análise estatística de quanto a passagem está mais barata em relação ao histórico recente.
- **Botões Inline:** Link direto que abre a página de reserva na viação/plataforma com um único toque.
