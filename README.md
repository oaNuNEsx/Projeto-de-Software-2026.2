# Analisador de Carteira e Estratégias de Cripto

Projeto em **Python** que modela uma carteira de criptoativos, regras de negociação,
avaliação de risco, estratégias de investimento e backtests. A integração externa é
feita com a API pública da **CoinGecko**.

A demonstração principal foi organizada por requisito funcional (**RF1 → RF10**),
facilitando tanto a apresentação no terminal quanto a apresentação do código.

## Como executar

Instale as dependências:

```bash
python -m pip install -r requirements.txt
```

Execute a demonstração:

```bash
python main.py
```

Execute os testes automatizados:

```bash
python -m pytest -q
```

Atualmente, a suíte possui **9 testes automatizados**.

> A maior parte das demonstrações usa dados controlados para não depender da rede.
> A demonstração do **RF8** usa a CoinGecko ao vivo e, portanto, precisa de internet.

---

## Menu de demonstração

Ao executar `python main.py`, o programa apresenta os requisitos na mesma ordem da
especificação:

```text
1.  RF1  — Carteira protegida
2.  RF2  — Sem mistura implícita de moedas
3.  RF3  — Histórico reprodutível
4.  RF4  — Tipos de criptoativos
5.  RF5  — Modelos de risco plugáveis
6.  RF6  — Erros de negociação distinguíveis
7.  RF7  — Trilha de auditoria imutável
8.  RF8  — Preços cientes de limite de requisições
9.  RF9  — Conjunto aberto de estratégias
10. RF10 — Torneio de estratégias
0.  Sair
```

Cada opção mostra também o arquivo/classe principal responsável pela implementação
do requisito, servindo como guia para a apresentação do código.

---

## Estrutura do projeto

```text
crypto_portfolio/
├── money.py          # RF2 — Amount e proteção contra mistura implícita de moedas
├── errors.py         # RF6 — exceções específicas para falhas de negociação
├── assets.py         # RF4 — Asset abstrata + Coin / Stablecoin / Token
├── audit.py          # RF7 — Trade imutável + AuditTrail
├── portfolio.py      # RF1 — Portfolio protegido e execute_trade()
├── risk_models.py    # RF5 — modelos de risco plugáveis
├── market_data.py    # RF3 — histórico imutável | RF8 — API, cache, rate limit e retry
├── strategies.py     # RF9 — Strategy + registro aberto de estratégias
└── tournament.py     # RF10 — execução e ranking das estratégias

main.py               # demonstração RF1 → RF10
tests/test_offline.py # testes automatizados sem dependência de rede
index.html            # diagrama do projeto
requirements.txt      # dependências
```

---

# Requisitos funcionais

## RF1 — Carteira protegida

**Código principal:** `crypto_portfolio/portfolio.py`

A classe `Portfolio` mantém caixa e posições protegidos. O estado da carteira muda
somente por operações controladas em `execute_trade()`.

Antes de modificar qualquer valor, a operação é validada. Se ocorrer uma falha,
a carteira permanece intacta.

Exemplo demonstrado:

- compra válida de BTC;
- tentativa de vender mais BTC do que existe na carteira;
- operação recusada;
- saldo e posições permanecem inalterados após a falha.

---

## RF2 — Sem mistura implícita de moedas

**Código principal:** `crypto_portfolio/money.py`

Valores monetários são representados por `Amount`.

Uma soma como:

```text
100 BRL + 20 USD
```

é rejeitada com `CurrencyMismatchError`.

A combinação só é permitida após uma conversão explícita:

```text
20 USD → BRL
100 BRL + valor convertido
```

Assim, o próprio projeto impede a mistura acidental de moedas diferentes.

---

## RF3 — Histórico reprodutível

**Código principal:** `crypto_portfolio/market_data.py`

`PricePoint` é imutável e `HistoricalSeries` armazena seus pontos em uma estrutura
que não pode ser alterada externamente.

A demonstração comprova que:

- um preço histórico não pode ser editado;
- não é possível adicionar pontos diretamente ao histórico obtido;
- executar o mesmo backtest duas vezes com o mesmo histórico e capital produz o
  mesmo resultado.

---

## RF4 — Tipos de criptoativos

**Código principal:** `crypto_portfolio/assets.py`

`Asset` é uma classe abstrata.

Os tipos:

- `Coin`
- `Stablecoin`
- `Token`

herdam de `Asset` e implementam seu próprio comportamento de risco.

Exemplos:

- `Coin`: considera volatilidade;
- `Stablecoin`: considera o desvio da paridade de USD 1;
- `Token`: combina volatilidade e penalidade de liquidez/ranking.

Todos respondem ao mesmo método `risk_score()`, demonstrando herança e polimorfismo.

---

## RF5 — Modelos de risco plugáveis

**Código principal:** `crypto_portfolio/risk_models.py`

A abstração `RiskModel` permite avaliar a mesma carteira usando modelos diferentes.

Modelos disponíveis:

- `ConservativeRiskModel`
- `AggressiveRiskModel`

O modelo é selecionado em tempo de execução por `get_risk_model()` sem modificar a
estrutura da carteira.

---

## RF6 — Erros de negociação distinguíveis

**Código principal:** `crypto_portfolio/errors.py` e `crypto_portfolio/portfolio.py`

As falhas possuem exceções específicas, entre elas:

- `AssetNotFoundError`
- `InsufficientBalanceError`
- `InsufficientPositionError`
- `InvalidQuantityError`
- `InvalidPriceError`
- `InvalidExchangeRateError`
- `RateLimitExceededError`

Isso permite distinguir situações diferentes, em vez de tratar qualquer falha como
um erro genérico.

---

## RF7 — Trilha de auditoria imutável

**Código principal:** `crypto_portfolio/audit.py`

Cada negociação concluída gera um `Trade`.

`Trade` é definido como imutável (`frozen=True`) e o `AuditTrail` expõe as
negociações apenas para leitura.

A demonstração realiza operações `BUY` e `SELL`, mantém ambas no histórico e comprova
que uma transação antiga não pode ser alterada.

Também não existem operações públicas de `remove`, `edit` ou `clear` no histórico.

### Observação

A trilha de auditoria é preservada durante a execução do programa. O projeto atual
não utiliza banco de dados ou arquivo persistente; portanto, ao encerrar e iniciar
uma nova execução, um novo estado em memória é criado.

---

## RF8 — Preços cientes de limite de requisições

**Código principal:** `crypto_portfolio/market_data.py`

Este é o requisito que demonstra diretamente a integração com a **CoinGecko**.

O `PriceService`:

- busca preços atuais;
- consulta BTC, ETH e USDT em lote;
- mantém cache com TTL;
- evita chamadas externas redundantes;
- usa `TokenBucketRateLimiter`;
- trata HTTP 429;
- respeita `Retry-After` quando fornecido;
- aplica backoff antes de novas tentativas.

Na demonstração, duas consultas iguais feitas em sequência reutilizam os dados em
cache.

---

# Uso da CoinGecko

A integração externa fica encapsulada em `crypto_portfolio/market_data.py`.

Os principais recursos utilizados são:

### Preços atuais

```text
/coins/markets
/simple/price
```

São usados para obter dados como:

- preço em USD;
- preço em BRL;
- variação de 24 horas;
- posição no ranking de capitalização.

### Histórico

```text
/coins/{coin_id}/market_chart
```

É usado pelo `HistoricalDataStore` para obtenção de séries históricas.

No `main.py` atual, dados controlados são usados em vários RFs para tornar as
demonstrações independentes de conexão e de variações externas. A CoinGecko real é
demonstrada diretamente no RF8.

---

## RF9 — Conjunto aberto de estratégias

**Código principal:** `crypto_portfolio/strategies.py`

A classe abstrata `Strategy` define o contrato comum das estratégias.

As implementações são registradas por `@register_strategy`.

Estratégias atuais:

- HODL
- DCA
- Rebalanceamento
- Stop-Loss

`available_strategies()` descobre as estratégias registradas sem exigir uma lista
fixa em outros módulos.

Assim, uma nova estratégia pode ser adicionada sem modificar as implementações
existentes.

---

## RF10 — Torneio de estratégias

**Código principal:** `crypto_portfolio/tournament.py`

`Tournament.run()` obtém as estratégias registradas por `available_strategies()` e
executa todas contra:

- o mesmo histórico;
- o mesmo capital inicial;
- as mesmas condições de simulação.

No final, os resultados são ordenados por retorno.

O torneio não conhece antecipadamente os nomes ou a quantidade de estratégias.
Portanto, uma nova estratégia registrada no RF9 passa automaticamente a participar
do RF10.

---

# Testes

Os testes ficam em:

```text
tests/test_offline.py
```

Eles foram construídos para validar as regras de negócio sem depender da internet.

Execute:

```bash
python -m pytest -q
```

Resultado esperado na versão atual:

```text
9 passed
```

A demonstração ao vivo do RF8 depende da CoinGecko e é executada pelo `main.py`.

---

# Mapa rápido para apresentação do código

| RF | Arquivo principal | Conceito central |
|---|---|---|
| RF1 | `portfolio.py` | encapsulamento e validação antes da mutação |
| RF2 | `money.py` | tipo monetário seguro e conversão explícita |
| RF3 | `market_data.py` | imutabilidade do histórico |
| RF4 | `assets.py` | abstração, herança e polimorfismo |
| RF5 | `risk_models.py` | estratégia/modelo plugável |
| RF6 | `errors.py` / `portfolio.py` | exceções específicas |
| RF7 | `audit.py` | registro imutável de negociações |
| RF8 | `market_data.py` | CoinGecko, cache, rate limit e retry |
| RF9 | `strategies.py` | registro aberto de estratégias |
| RF10 | `tournament.py` | execução uniforme e ranking |

---

# Limitações conhecidas

- A CoinGecko pública possui limites de requisição. O projeto reduz esse problema
  com cache, rate limiter e retry, mas a disponibilidade final ainda depende do
  serviço externo.
- A trilha de auditoria é imutável durante a execução, mas ainda não é persistida em
  banco de dados ou arquivo entre execuções.
- O backtest é uma simulação educacional e não considera todas as condições de uma
  corretora real, como taxas, slippage e latência.
