# 🧠 Motor de Decisão e Estratégia de Compra

Este documento detalha o funcionamento matemático e lógico do módulo `analyzer.py`, responsável por classificar se um bilhete rodoviário está no **melhor momento de compra**, se deve ser monitorado ou se exige ação urgente devido à escassez de vagas.

---

## 1. Princípios de Decisão

O algoritmo avalia cada trecho (*leg*) combinando três eixos fundamentais:
1. **Janela Temporal (Dias Restantes - $D$):** Quão perto a data da viagem está da data atual.
2. **Faixa de Preço (Target Prices e Estatística):**
   - $P_{\text{excelente}}$ (`TARGET_PRICE_EXCELLENT`): Preço considerado excepcional/raro.
   - $P_{\text{bom}}$ (`TARGET_PRICE_GOOD`): Teto para considerar uma tarifa justa e recomendável.
   - $\mu$ (Média Móvel Histórica) e $\sigma$ (Desvio Padrão) nos últimos 14 a 30 dias.
3. **Disponibilidade Real de Vagas:** Número de assentos livres na opção mais barata dentro da janela estrita de horários.

---

## 2. Níveis de Classificação (Prioridade Decrescente)

A avaliação ocorre em cascata determinística. A primeira condição satisfeita define o nível da recomendação:

```
[ Início ]
   │
   ├─► 0. Não há opções na janela? ─────────────────► ⚪ SEM DADOS
   │
   ├─► 1. Vagas <= MIN_SEATS_CRITICAL (reais)? ─────► 🔴 ÚLTIMAS VAGAS
   │
   ├─► 2. Condição de Compra Imediata satisfeita? ──► 🟢 COMPRA RECOMENDADA
   │      ├─ Preço <= TARGET_PRICE_EXCELLENT
   │      ├─ Preço <= TARGET_PRICE_GOOD E (D <= 15 OU mínima histórica OU P <= μ - 0.5σ)
   │      ├─ Faltam <= 3 dias (D <= 3, urgência temporal)
   │      └─ Faltam <= 7 dias E mínima histórica observada
   │
   ├─► 3. Preço <= TARGET_PRICE_GOOD? ──────────────► 🟢 PREÇO BOM
   │
   ├─► 4. Faltam mais de 15 dias (D > 15)? ─────────► 🟡 AGUARDAR / MONITORAR
   │
   └─► 5. Nenhuma das anteriores ───────────────────► 🟠 PREÇO ACIMA DO ALVO
```

---

## 3. Tratamento Especial de Assentos (Display Cap)

Muitas empresas (como a Buser no modelo de fretamento) limitam visualmente a exibição de assentos no front-end para um teto fixo (ex: exibe `13` mesmo que existam 30 poltronas livres).

- O `Offer` identifica quando o número de assentos é limitado (`seats_capped = True`).
- **Gatilho de Proteção:** O status `🔴 ÚLTIMAS VAGAS` **só dispara** se as vagas reportadas forem uma contagem exata e irrestrita menor ou igual ao limiar configurado (`MIN_SEATS_CRITICAL`, padrão: 5). Se for um teto artificial, evita-se o envio de alarmes falsos de urgência.

---

## 4. Política Anti-Spam e Gatilhos de Notificação

No `notifier.py`, os alertas do Telegram seguem regras rígidas para não sobrecarregar o usuário:

1. **Mudança de Nível de Urgência:** Se uma passagem passa de `🟡 AGUARDAR` para `🟢 COMPRA RECOMENDADA` ou `🔴 ÚLTIMAS VAGAS`, a notificação é disparada imediatamente.
2. **Queda Relevante de Preço:** Se o preço cair mais do que o valor definido em `PRICE_DROP_ALERT` (ex: queda ≥ R$ 5,00) em relação ao último alerta enviado.
3. **Marcos de Proximidade (Milestones):** Notificações nos marcos $D \in \{30, 15, 7, 3, 1\}$ dias antes do embarque, disparando apenas se o preço estiver no patamar `BOM` ou se faltarem 3 dias ou menos.
4. **Silenciamento por Compra (`/comprei`):** Quando o usuário emite o comando `/comprei <id> [ida|volta]`, a chave é persistida no banco SQLite e todos os alertas subsequentes desse trecho são desativados.
