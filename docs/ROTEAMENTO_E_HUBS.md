# 🧭 Roteamento Inteligente & Hubs Regionais

Este documento detalha o funcionamento do algoritmo em `routing.py`, projetado para resolver um problema comum em transporte rodoviário: **a ausência de linhas diretas ou de horários viáveis entre certas cidades**.

---

## 1. O Desafio da Conectividade Rodoviária

Nem todas as conexões entre municípios possuem linhas diretas frequentes ou nos horários desejados pelo usuário (por exemplo, viagens na madrugada para chegar cedo ao destino). Muitas vezes, a alternativa mais rápida e barata consiste em viajar até uma cidade vizinha maior (um **Hub Regional**) e de lá fazer um deslocamento curto até o destino final.

---

## 2. Topologias de Rota Suportadas

O sistema suporta até três formas de composição de itinerário:

### 2.1. Rota Direta (Sem Conexões)
- Uma única perna direta consultada nos provedores de busca:
  $$\text{Origem} \xrightarrow{\text{Ônibus Direto}} \text{Destino}$$

### 2.2. Hub com Conexão Local Estimada (`LOCAL_CONNECTIONS`)
- Se o usuário configurou uma estimativa de conexão local no `.env` (ex: ônibus municipal, intermunicipal metropolitano ou transporte por aplicativo entre cidades vizinhas), o sistema costura automaticamente o trecho rodoviário principal com o trecho local:
  
  **Caso A (Hub Próximo ao Destino):**
  $$\text{Origem} \xrightarrow{\text{Ônibus Rodoviário}} \text{Hub} \xrightarrow{\text{Conexão Local (Estimada)}} \text{Destino}$$
  
  **Caso B (Hub Próximo à Origem):**
  $$\text{Origem} \xrightarrow{\text{Conexão Local (Estimada)}} \text{Hub} \xrightarrow{\text{Ônibus Rodoviário}} \text{Destino}$$

- O custo estimado da conexão é somado ao valor total do itinerário.
- A hora estimada de chegada/saída inclui um intervalo seguro configurado para o desembarque e transbordo.

### 2.3. Baldeação Rodoviária Real (Duas Linhas)
- Se nenhuma conexão local estimada estiver cadastrada para o hub, o sistema consulta os provedores para os dois trechos:
  $$\text{Origem} \xrightarrow{\text{Linha 1}} \text{Hub} \xrightarrow{\text{Linha 2}} \text{Destino}$$
- **Critérios de Validade da Conexão:**
  - O intervalo entre a chegada da Linha 1 e a partida da Linha 2 deve respeitar:
    $$\text{MIN\_CONNECTION\_MINUTES} \le (\text{Partida}_2 - \text{Chegada}_1) \le 6\text{ horas}$$
  - Baldeações onde a segunda viagem parte antes do tempo mínimo de segurança (ex: 30 minutos) são descartadas para evitar perda do ônibus.

---

## 3. Janelas Horárias e Travessia de Meia-Noite

O modelo `LegSpec` gerencia de forma inteligente viagens noturnas e de madrugada:
- Se a janela de partida estiver definida com horário final menor que o inicial (ex: saída após 22:00 e antes de 02:00):
  - O sistema detecta automaticamente que a janela atravessa a meia-noite (`crosses_midnight = True`).
  - As buscas na API cobrem **tanto a data inicial quanto o dia seguinte**.
- Se for definido um limite de chegada no dia seguinte (`arrive_day_offset = 1`), o itinerário só é aceito se a chegada for anterior ao horário limite exigido (por exemplo, chegar até 07:15 da manhã para conseguir trabalhar às 08:00).
