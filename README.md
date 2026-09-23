# Analisador de Carteira e Estratégias de Cripto

Programa em Python que usa a API da **CoinGecko** para
simular uma carteira de criptoativos, avaliar risco sob modelos plugáveis,
e rodar um torneio entre estratégias de investimento contra dados históricos.

## Como rodar

```bash
python -m pip install -r requirements.txt
python main.py             # demo completa; precisa de internet
python -m pytest -q        # testes automatizados; não precisam de internet
```

## Estrutura

```
crypto_portfolio/
├── money.py           # RF2 — Amount (valor + moeda), soma entre moedas diferentes é impossível
├── errors.py          # RF6 — uma classe de exceção por tipo de falha de negociação
├── assets.py          # RF4 — Asset + risco calculado de forma diferente por tipo (COIN/STABLECOIN/TOKEN)
├── audit.py           # RF7 — Trade (frozen) + AuditTrail (só permite record(), nunca editar/apagar)
├── portfolio.py        # RF1 — Portfolio com estado privado; única porta de escrita é execute_trade()
├── risk_models.py      # RF5 — RiskModel plugável (ConservativeRiskModel, AggressiveRiskModel)
├── strategies.py        # RF9 — Strategy + registro via @register_strategy (HODL, DCA, Rebalanceamento, Stop-Loss)
├── market_data.py       # RF3 (histórico imutável) + RF8 (cache + rate limit + retry no PriceService)
└── tournament.py         # RF10 — roda todas as estratégias registradas contra o mesmo histórico
main.py                   # demo end-to-end com a API real da CoinGecko
tests/test_offline.py      # valida as regras de negócio com dados simulados (não depende de rede)
```

## Como cada requisito foi resolvido

- **RF1 (carteira protegida):** `Portfolio` guarda `__cash`/`__positions` como
  atributos privados (name-mangled), sem nenhum setter público. A única forma
  de mudar o estado é `execute_trade()`, que valida tudo *antes* de mutar
  qualquer coisa. Se a validação falhar, uma exceção é lançada e o estado
  permanece intocado — não existe caminho de código que atribua posição/saldo
  diretamente.

- **RF2 (sem mistura implícita de moedas):** todo valor monetário é um
  `Amount(valor, moeda)`. `Amount.__add__` e os comparadores levantam
  `CurrencyMismatchError` se as moedas forem diferentes. A única forma de
  "misturar" moedas é `Amount.convert_to(moeda_alvo, taxa)`, uma conversão
  sempre explícita.

- **RF3 (histórico reprodutível):** `HistoricalSeries` guarda os pontos em uma
  tupla de `PricePoint` (`@dataclass(frozen=True)`) — imutável por construção.
  `HistoricalDataStore.fetch()` mantém cache por `(ativo, período)`. Chamadas
  seguintes para o mesmo ativo e o mesmo número de dias devolvem a mesma
  série já armazenada; períodos diferentes, como 30 e 180 dias, ficam
  separados. Assim o backtest continua reprodutível sem misturar históricos.

- **RF4 (tipos de ativos):** `AssetType.COIN` usa volatilidade de 24h;
  `AssetType.STABLECOIN` usa o desvio da paridade de 1 USD (uma stablecoin a
  $0,97 pontua mais risco que uma a $1,00 mesmo com baixa volatilidade
  numérica); `AssetType.TOKEN` combina volatilidade com uma penalidade de
  liquidez/capitalização.

- **RF5 (modelos de risco plugáveis):** `RiskModel` é uma interface (ABC).
  `ConservativeRiskModel` pune concentração (peso ao quadrado) com limiares de
  classificação mais baixos; `AggressiveRiskModel` usa média ponderada simples
  com limiares mais altos. `get_risk_model(nome)` troca o modelo com uma única
  chamada — a mesma carteira 70% BTC / 30% ETH sai como **AGRESSIVA** no
  modelo conservador e **ACEITÁVEL** no agressivo.

- **RF6 (erros distinguíveis):** `AssetNotFoundError`, `InsufficientBalanceError`,
  `InsufficientPositionError`, `InvalidQuantityError`, `InvalidPriceError`,
  `InvalidExchangeRateError` e `RateLimitExceededError` são classes de exceção
  separadas (todas de `TradingError`), permitindo `except` específico em
  qualquer camada acima.

- **RF7 (auditoria imutável):** `Trade` é `frozen=True`. `AuditTrail` só expõe
  `record()` (escreve) e `entries` (lê uma cópia em tupla) — não existe
  `remove`/`edit`/`clear`, nem na própria `Portfolio`.

- **RF8 (preços cientes de rate limit):** `PriceService.get_prices()` deduplica
  os `coin_ids` pedidos e usa cache com TTL curto, então N estratégias pedindo
  o mesmo preço no mesmo instante geram 1 chamada, não N. Um
  `TokenBucketRateLimiter` limita chamadas/minuto; se a API responder 429, o
  serviço espera (`Retry-After` ou backoff exponencial) e tenta de novo, em
  vez de falhar.

- **RF9 (estratégias abertas):** `Strategy` é uma interface; o decorator
  `@register_strategy` registra a classe num dicionário global. `HodlStrategy`,
  `DcaStrategy`, `RebalanceStrategy` e `StopLossStrategy` (a "estratégia da
  semana 7") coexistem sem nenhuma referência umas às outras.

- **RF10 (torneio):** `Tournament.run()` chama `available_strategies()` e itera
  sobre o que vier — nunca com uma lista fixa de nomes. Todas as estratégias
  começam da mesma carteira-base: por padrão, 35% em BTC, 35% em ETH e 30%
  em caixa. A variação de 24h é calculada a partir do histórico, permitindo
  que estratégias como HODL e Stop-Loss sejam realmente exercitadas. Adicionar
  uma nova `@register_strategy` faz com que ela apareça automaticamente na
  classificação.

## Limitações conhecidas

- A CoinGecko pública tem limites de requisição informais (~10-30/min); os
  parâmetros de `PriceService`/`HistoricalDataStore` podem ser ajustados
  (`max_calls_per_minute`, `cache_ttl`) conforme necessário.
- O torneio (RF10) simula as estratégias reagindo apenas a preço; regras de
  execução mais realistas (taxas, slippage) podem ser adicionadas dentro de
  `Portfolio.execute_trade` sem alterar as estratégias.
