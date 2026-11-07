# 🖥️ Modos de Uso: Ambiente Gráfico (Web UI), Menu de Terminal (TUI) e CLI

O **BusTracker** oferece **três interfaces complementares** sobre o mesmo motor e banco de dados SQLite, permitindo usar a ferramenta da forma mais confortável em cada situação (no desktop Pop!_OS, no celular via Termux ou em scripts automatizados).

Use o atalho `./bustracker` na raiz do projeto (ele ativa automaticamente o ambiente virtual `.venv`):

```bash
./bustracker          # 1. Abre o Menu Interativo de Terminal (TUI)
./bustracker gui      # 2. Abre o Ambiente Gráfico no Navegador (Web UI)
./bustracker check    # 3. Executa comando direto via CLI
```

---

## 1. 🌐 Ambiente Gráfico no Navegador (`./bustracker gui`)

Ideal para usar no computador (**Pop!_OS / Linux**) ou acessar pelo navegador do celular quando quiser uma experiência 100% visual.

```bash
./bustracker gui
# Ou especifique porta/host (ex.: para abrir no navegador do celular via Wi-Fi):
./bustracker gui --host 0.0.0.0 --port 8080 --no-browser
```

### O que você encontra no Ambiente Gráfico:
1. **📊 Painel & Alertas:**
   - Indicadores rápidos (Total de trechos monitorados, Menor preço atual, Metas de preço Bom/Excelente e status do Telegram).
   - Cartões visuais com semáforo de recomendação (`🟢 COMPRA RECOMENDADA`, `🟡 AGUARDAR`, `🔴 ÚLTIMAS VAGAS`).
   - Botões de 1 clique: **🔄 Atualizar Preços Agora**, **🔗 Comprar na Buser**, **📈 Gráfico**, **✅ Já Comprei** e **🗑️ Remover**.
2. **📅 Calendário Visual Interativo (Mês a Mês):**
   - Grade mensal mostrando visualmente os dias de `➡️ Ida` e `⬅️ Volta` de todas as viagens cadastradas.
   - **Agendamento com 1 clique:** Ao clicar em qualquer dia do calendário, os formulários laterais (*Agendar Compromisso/Prova* e *Agendar Viagem Personalizada*) são preenchidos automaticamente com aquela data.
3. **🔎 Buscar Passagens em Tempo Real:**
   - Pesquisa visual com autocompletar de cidades, seletor de data, filtro de horários de partida e hubs alternativos.
4. **📈 Histórico & Gráfico (SVG):**
   - Gráfico visual da curva de preços coletados ao longo dos dias comparado à linha tracejada da sua meta de `Preço Bom`.
5. **⚙️ Configurações (.env / iCal):**
   - Edite sua rota padrão, janelas de horário seguras, preços-alvo, link `.ics` do Google Calendar e credenciais do Telegram diretamente pela tela, sem precisar abrir arquivos de texto.

---

## 2. 📱 Menu Interativo de Terminal — TUI (`./bustracker`)

Ideal para uso rápido no terminal ou dentro do **Termux no Android**, sem precisar decorar ou digitar comandos grandes!

Basta rodar:
```bash
./bustracker
```

Você verá um menu numerado amigável:
```text
╔══════════════════════════════════════════════════════════════╗
║ 🚌 BusTracker — Central Interativa de Passagens              ║
╚══════════════════════════════════════════════════════════════╝
  📍 Rota Padrão: São Paulo - SP ↔ Rio de Janeiro - RJ
  🎯 Preço Alvo : Bom ≤ R$ 80,00 | Excelente ≤ R$ 70,00
  🗂️ Viagens    : 2 ativa(s)   •   🤖 Telegram: Ativo

  [1] 📊 Ver Status e Recomendações (Última Coleta)
  [2] 🔄 Atualizar Preços Agora (Consultar Viações)
  [3] 🔎 Busca Rápida de Passagens (Qualquer Cidade/Data)
  [4] 📅 Agendar Compromisso / Prova (Calcula Ida D-1 e Volta D0)
  [5] ➕ Agendar Viagem Personalizada (Ida e Volta)
  [6] 🗂️ Gerenciar Minhas Viagens (Listar / Já Comprei / Remover)
  [7] 📁 Importar Calendário por Arquivo (.ics / .json)
  [8] 📈 Ver Gráfico de Histórico de Preços
  [9] ⚙️ Configurar Rota, Preços, Calendário (.ics) e Telegram
  [W] 🌐 Abrir Ambiente Gráfico no Navegador (Web UI)
  [0] 🚪 Sair
```

### Vantagens do Menu Interativo:
- **Zero digitação repetitiva:** Pressione `Enter` em qualquer pergunta para aceitar o valor padrão do seu `.env`.
- **Seleção de cidades por número:** Na busca ou cadastro, escolha `[1] São Paulo - SP`, `[2] Rio de Janeiro - RJ`, `[3] Belo Horizonte - MG`, `[4] Curitiba - PR`, etc., digitando apenas 1 dígito.
- **Datas curtas:** Aceita apenas `DD/MM` (ex.: `23/11`), preenchendo o ano automaticamente.
- **Gerenciamento sem IDs:** Na opção `[6]` ou `[7]`, você seleciona a viagem digitando `1`, `2`, `3`... em vez de copiar códigos como `cli-a1b2c3`.

---

## 3. ⚡ Linha de Comando Direta — CLI (Para Automação e Scripts)

Todos os comandos diretos continuam disponíveis para uso em scripts, `cron` ou `systemd`:

```bash
./bustracker --run-once                                              # Coleta única + alertas Telegram
./bustracker --daemon                                                # Robô 24/7 + Bot do Telegram
./bustracker status                                                  # Resumo imediato no terminal
./bustracker import /caminho/meu_calendario.ics                      # Importa arquivo .ics ou .json
./bustracker search sao-paulo-sp rio-de-janeiro-rj 23/11            # Busca direta
./bustracker event 24/11 --name "Prova Bimestral"                    # Agenda compromisso (Ida D-1, Volta D0)
./bustracker add 23/11 24/11 --name "Viagem Fim de Ano"              # Agenda viagem manual
./bustracker history                                                 # Gráfico ASCII no terminal
./bustracker sync                                                    # Sincroniza JSON e Google Calendar (.ics)
```
