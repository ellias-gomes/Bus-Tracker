# 🚍 Catálogo & Arquitetura de Provedores Rodoviários (Providers)

O **BusTracker** adota uma arquitetura modular de coleta multi-provedor assíncrona. Cada viação ou agregador é implementado como um conector independente herdando de `BaseProvider`, padronizando todas as ofertas no modelo canônico `Offer`.

---

## 1. Visão Geral da Arquitetura

```
                     +---------------------------------------+
                     |             Orquestrador              |
                     +---------------------------------------+
                                         |
                                         v
                         search_all(origin, dest, date)
                                         |
         +-------------------+-----------+-----------+-------------------+
         |                   |                       |                   |
         v                   v                       v                   v
+-----------------+ +-----------------+     +-----------------+ +-----------------+
|  BuserProvider  | |GuanabaraProvider|     | CometaProvider  | |AguiaBrancaProv. |
| (SSR Nuxt/Deval)| |(REST API Nextjs)|     | (REST API JCA)  | |(SAP Hybris OCC) |
+-----------------+ +-----------------+     +-----------------+ +-----------------+
         |                   |                       |                   |
         +-------------------+-----------+-----------+-------------------+
                                         |
                                         v
                            list[Offer] padronizado
```

### Características Gerais
- **Alta Performance:** Execução concorrente com `asyncio.gather(return_exceptions=True)`. Se um provedor oscilar temporariamente ou sofrer instabilidade na rede externa, os demais provedores continuam coletando normalmente sem interromper o fluxo.
- **Sessão HTTP Eficiente:** Compartilhamento de `HttpSession` assíncrona com pool de conexões persistentes, cabeçalhos modernos imitando navegadores reais e timeouts rígidos.
- **Normalização de Cidades:** Resolução automática de identificadores através do `CityCatalog` e dicionários de mapeamento específicos por empresa.

---

## 2. Provedores Integrados

### 2.1. 🟢 Buser (`BuserProvider`)
- **Tipo:** Fretamento colaborativo e marketplace de revenda rodoviária.
- **Mecanismo:** Extração direta via requisição HTTP leve sobre a página SSR Nuxt 3 (`/onibus/{origem}/{destino}?data={data}`).
- **Tecnologia:** Parser nativo do payload de serialização `@nuxt/devalue` (`utils/nuxt.py`), eliminando a necessidade de emuladores pesados de navegador como Puppeteer ou Selenium.
- **Tratamento de Assentos:** A Buser costuma exibir um teto visual fixo de assentos livres (ex.: `13`). O parser detecta e sinaliza `seats_capped = True`, impedindo falsos alarmes de escassez no motor de decisão.

### 2.2. 🟡 Viação Guanabara (`GuanabaraProvider`)
- **Empresas atendidas:** Viação Guanabara, Util, Sampaio e Real Expresso.
- **Mecanismo:** Requisições REST diretas ao backend Next.js da plataforma:
  ```http
  GET https://viaje-next.viajeguanabara.com.br/api/trips?origin=SAO+PAULO+-+SP&destination=RIO+DE+JANEIRO+-+RJ&date=YYYY-MM-DD
  ```
- **Normalização:** Conversão de slugs do BusTracker para o padrão da API Guanabara (`CIDADE - UF` em maiúsculas).
- **Mapeamento:** Suporte a poltronas Convencional, Executivo, Semi-Leito, Leito e Cama.

### 2.3. 🔴 Viação Cometa / Grupo JCA (`CometaProvider`)
- **Empresas atendidas:** Viação Cometa, Auto Viação 1001, Catarinense e Rápido Ribeirão.
- **Mecanismo:** REST API oficial de vendas do Grupo JCA:
  - Consulta e mapeamento de IDs de localidade (`/v1/sales/places/search`).
  - Consulta de viagens disponíveis:
  ```http
  GET https://api.viacaocometa.com.br/v1/sales/trips?originPlaceId={origId}&destinationPlaceId={destId}&departureDate=YYYY-MM-DD
  ```
- **Destaque:** Cache automático de IDs de praça para minimizar chamadas adicionais e cálculo preciso de assentos livres por serviço.

### 2.4. 🦅 Viação Águia Branca (`AguiaBrancaProvider`)
- **Empresas atendidas:** Linhas interestaduais e estaduais da Viação Águia Branca (SP, RJ, MG, ES, BA).
- **Mecanismo:** API oficial baseada em **SAP Commerce Cloud (Hybris OCC)**:
  ```http
  GET https://api.aguiabranca.com.br/rest/v2/aguiabranca/trips?origin={orig}&destination={dest}&departureDate=YYYY-MM-DD
  ```
- **Recursos:** Extração detalhada de taxas de embarque, conexões operacionais, horários de saída/chegada e disponibilidade real de poltronas leito/semi-leito.

---

## 3. Extensibilidade & Novos Conectores

Adicionar uma nova empresa ou agregador ao BusTracker requer apenas 3 etapas:

1. **Criar a classe herdando de `BaseProvider`:**
   ```python
   # src/bustracker/providers/minha_viacao.py
   from bustracker.models import Offer
   from bustracker.providers.base import BaseProvider

   class MinhaViacaoProvider(BaseProvider):
       name = "minha_viacao"

       async def search_trips(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
           # 1. Montar payload / URL
           # 2. Executar self.session.get(...) ou self.session.post(...)
           # 3. Mapear resposta para list[Offer]
           return []
   ```

2. **Registrar no catálogo:**
   Em `src/bustracker/providers/__init__.py`:
   ```python
   PROVIDERS_REGISTRY["minha_viacao"] = MinhaViacaoProvider
   ```

3. **Escrever os testes unitários:**
   Adicionar fixtures em `tests/test_new_providers.py` com mocks dos payloads JSON/HTML para garantir estabilidade e regressão zero.
