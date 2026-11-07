# Sistema de Monitoramento e Otimização de Passagens Rodoviárias

## 1. Visão Geral
Sistema automatizado e multiplataforma para monitoramento diário, análise preditiva de preços e notificação inteligente de passagens de ônibus rodoviários. Projetado para rodar de forma leve e resiliente em ambientes Linux (Pop!_OS, Ubuntu, Debian) e dispositivos móveis (Android via Termux), com baixo consumo de memória e CPU.

---

## 2. Objetivos Principais
- **Monitoramento Diário:** Coleta automática de tarifas, horários, conexões e vagas disponíveis.
- **Modelo de Decisão de Compra ("Momento Ideal"):**
  - **Classificador Baseado em Regras e Histórico:**
    - Faixa de corte alvo (Target Price): Abaixo de R$ 80,00 (Ótimo: ≤ R$ 70,00).
    - Desvio padrão e média móvel dos últimos 14 a 30 dias.
    - Curva de urgência temporal (D-30, D-15, D-7, D-3) cruzada com a taxa de ocupação dos assentos.
- **Roteamento Inteligente & Hubs Regionais:**
  - Suporte a busca direta e rotas com até 1 conexão/hub próximo (ex: desembarque em Campinas - Rodoviária + custo estimado/baldeação para Jundiaí).
  - Cálculo de custo-benefício (Custo Total vs. Tempo de Deslocamento).
- **Gestão de Viagens Multi-Fonte:**
  - Sincronização via calendário remoto iCal / Google Calendar (.ics).
  - Gestão declarativa via arquivo local (`viagens.json` / `viagens.yaml`).
  - Gestão interativa via comandos de Telegram Bot (`/nova_viagem`, `/listar`, `/remover`).
- **Alertas Automatizados via Telegram:**
  - Notificações de oportunidade de preço.
  - Alerta de aproximação de data com vagas acabando.
  - Resumo matinal diário de rotas monitoradas.

---

## 3. Arquitetura da Solução

```
+---------------------------------------------------------------------------------+
|                    Agendador / Daemon (Cron Linux ou Termux Job)                |
+---------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------+
|                               Orquestrador Core                                 |
+---------------------------------------------------------------------------------+
          |                                      |                          |
          v                                      v                          v
+-----------------------+              +--------------------+     +-------------------+
| Provedor de Agendas   |              |  Mecanismo Scraper |     |  Telegram Bot     |
| - Google Cal (iCal)   |              |  - Buser API       |     |  - Notificações   |
| - viagens.json local  |              |  - Guanabara API   |     |  - Comandos       |
| - Telegram input      |              |  - Cometa (JCA) API|     |    interativos    |
+-----------------------+              |  - Águia Branca API|     +-------------------+
                                       |  - ClickBus / PM   |
                                       +--------------------+
                                                 |
                                                 v
                                       +--------------------+
                                       |  Banco de Dados    |
                                       |  (SQLite local)    |
                                       +--------------------+
                                                 |
                                                 v
                                       +--------------------+
                                       | Motor de Análise   |
                                       | & Decisão de Preço |
                                       +--------------------+
```

---

## 4. Módulos do Sistema

### 4.1. Módulo de Coleta (Providers)
- **Buser Provider:** Extração via endpoints públicos/APIs internas consumidas pelo web/app (fretamento colaborativo e marketplace).
- **Guanabara Provider:** Coleta de linhas regulares da Viação Guanabara, Util, Sampaio e Real Expresso via REST API Next.js.
- **Cometa Provider:** Coleta de linhas regulares do Grupo JCA (Viação Cometa, 1001, Catarinense) via REST API oficial JCA.
- **Águia Branca Provider:** Coleta de passagens via API oficial SAP Commerce Cloud (Hybris).
- **ClickBus / Pássaro Marron:** Conectores adicionais/experimentais preparados.
- **Tratamento de Anti-Bloqueio & Leveza:**
  - Uso preferencial de requisições HTTP diretas (`httpx` / `requests`) com simulação de headers.
  - Fallback headless browser apenas quando estritamente necessário, otimizado para não sobrecarregar dispositivos Termux/ARM.

### 4.2. Módulo de Roteamento & Proximidade
- Matriz de nós de transporte configurável pelo usuário:
  - Nó Origem: Cidade de partida (ex: São Paulo - Rodoviária Tietê / Barra Funda).
  - Nó Destino Principal: Cidade de destino (ex: Rio de Janeiro - Novo Rio).
  - Nó Alternativo (Hub): Cidades intermediárias ou polos regionais vizinhos (ex: Campinas, Volta Redonda).
- Algoritmo de junção: Se não houver direto no horário desejado, calcula o trecho até o hub + baldeação ou conexão local estimada.

### 4.3. Motor Analítico de Compra
- **Regra de Janela Crítica:**
  - Janela de Ida: Viagem com embarque restrito a horários convenientes/seguros (ex.: saída antes das 22h00).
  - Janela de Volta: Viagem noturna com chegada no destino final antes do início do expediente de trabalho (ex.: até 07h15 da manhã).
- **Classificação do Bilhete:**
  - 🟢 **COMPRA RECOMENDADA (Melhor Momento):** Preço ≤ R$ 80,00 e vagas em ritmo de ocupação normal ou acelerado.
  - 🟡 **AGUARDAR / MONITORAR:** Preço > R$ 80,00 com mais de 15 dias de antecedência e volume alto de assentos livres.
  - 🔴 **ALERTA CRÍTICO (Últimas Vagas):** Menos de 5 assentos disponíveis dentro da janela de horário estrita, independente do preço.

### 4.4. Módulo de Calendário Híbrido
- Sincronizador unificado que consolida:
  1. Feeds iCal remotos (.ics).
  2. Arquivo estático versionável `data/viagens.json`.
  3. Registros persistidos criados on-the-fly pelo Telegram.

### 4.5. Interface Telegram
- Notificação push com botões inline: [Comprar no Site], [Ignorar Viagem], [Ver Histórico].
- Comandos suportados:
  - `/status` - Mostra a próxima viagem programada e o menor preço atual.
  - `/adicionar AAAA-MM-DD [destino]` - Registra uma nova data no monitoramento.
  - `/historico` - Gráfico simples em texto/tabela com os preços dos últimos 14 dias.

---

## 5. Especificações Técnicas & Compatibilidade (Linux & Termux)
- **Linguagem:** Python 3.10+ (Totalmente compatível com Pop!_OS e Termux no Android).
- **Banco de Dados:** SQLite nativo (sem necessidade de instalar serviços pesados como Docker/Postgres).
- **Consumo de Recursos:** Memória RAM < 80MB durante a execução; processo leve que acorda via cron diário ou roda como daemon assíncrono.
- **Estrutura de Arquivos:** Modular, testável e desacoplada de credenciais.
