"""
main.py
-------
Demonstração orientada pelos Requisitos Funcionais (RF1 -> RF10).

Objetivo desta versão:
- permitir que o professor peça qualquer RF diretamente pelo número;
- manter as demonstrações pequenas, determinísticas e fáceis de explicar;
- reutilizar a mesma carteira durante a sessão quando isso ajuda (RF1/RF7);
- usar a CoinGecko somente onde a API faz parte do requisito (RF8), reduzindo
  risco de rate limit durante a apresentação;
- indicar na tela o arquivo/classe principal de cada requisito, servindo também
  como guia para a apresentação de código.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from decimal import Decimal, InvalidOperation

import requests

from crypto_portfolio.assets import DEFAULT_ASSET_REGISTRY
from crypto_portfolio.audit import TradeSide
from crypto_portfolio.errors import TradingError
from crypto_portfolio.market_data import (
    HistoricalSeries,
    MarketPoint,
    PricePoint,
    PriceService,
)
from crypto_portfolio.money import Amount, CurrencyMismatchError
from crypto_portfolio.portfolio import Portfolio
from crypto_portfolio.risk_models import get_risk_model
from crypto_portfolio.strategies import available_strategies
from crypto_portfolio.tournament import Tournament


COIN_IDS = ["bitcoin", "ethereum", "tether"]


@dataclass
class DemoState:
    """Estado compartilhado apenas durante a execução do programa."""

    portfolio: Portfolio | None = None
    last_price_usd: Decimal = Decimal("85000")
    last_fx_usd_to_brl: Decimal = Decimal("5.10")


def linha(titulo: str) -> None:
    print("\n" + "=" * 78)
    print(titulo)
    print("=" * 78)


def codigo_principal(texto: str) -> None:
    print(f"  Código principal: {texto}\n")


def formatar_numero_br(valor: Decimal, casas: int = 2) -> str:
    texto = f"{Decimal(valor):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def ler_decimal(mensagem: str, padrao: str) -> Decimal:
    """Lê Decimal positivo; Enter usa o valor padrão."""
    while True:
        texto = input(f"{mensagem} [padrão: {padrao}]: ").strip()
        if not texto:
            texto = padrao
        try:
            valor = Decimal(texto.replace(",", "."))
            if valor <= 0:
                raise ValueError
            return valor
        except (InvalidOperation, ValueError):
            print("  Valor inválido. Digite um número maior que zero.")


def ler_ativo(padrao: str = "bitcoin") -> str:
    while True:
        texto = input(
            f"Ativo (bitcoin/ethereum/tether) [padrão: {padrao}]: "
        ).strip().lower()
        ativo = texto or padrao
        if ativo in COIN_IDS:
            return ativo
        print("  Ativo inválido. Use bitcoin, ethereum ou tether.")


def mostrar_estado_carteira(portfolio: Portfolio) -> None:
    print(
        f"  Caixa: {portfolio.cash.currency} "
        f"{formatar_numero_br(portfolio.cash.value)}"
    )
    positions = portfolio.positions
    if positions:
        print("  Posições:")
        for asset_id, quantidade in positions.items():
            print(f"    - {asset_id}: {quantidade}")
    else:
        print("  Posições: nenhuma")
    print(f"  Negociações concluídas: {len(portfolio.audit_trail)}")


def mostrar_trade(trade) -> None:
    total_usd = trade.quantity * trade.price_usd
    print(
        f"    {trade.trade_id} | {trade.side.value:4s} | "
        f"{trade.quantity} {trade.asset_id}"
    )
    print(f"      Preço unitário: USD {formatar_numero_br(trade.price_usd)}")
    print(f"      Valor da operação: USD {formatar_numero_br(total_usd)}")
    print(
        f"      Valor convertido: {trade.cash_currency} "
        f"{formatar_numero_br(trade.cash_amount)}"
    )


def snapshot_sintetico() -> dict[str, MarketPoint]:
    """Dados determinísticos para demonstrar regras sem depender da rede."""
    return {
        "bitcoin": MarketPoint(
            Decimal("60000"), Decimal("300000"), Decimal("5"), 1
        ),
        "ethereum": MarketPoint(
            Decimal("3000"), Decimal("15000"), Decimal("8"), 2
        ),
        "tether": MarketPoint(
            Decimal("0.97"), Decimal("4.85"), Decimal("0.1"), 5
        ),
        "dogecoin": MarketPoint(
            Decimal("0.12"), Decimal("0.60"), Decimal("12"), 150
        ),
    }


def historicos_sinteticos() -> dict[str, HistoricalSeries]:
    """Histórico determinístico com uma queda forte para exercitar Stop-Loss."""
    day = 86_400_000
    btc_points: list[PricePoint] = []
    eth_points: list[PricePoint] = []

    for i in range(30):
        if i < 10:
            btc = Decimal(100 + i * 2)
        elif i == 10:
            btc = Decimal("80")  # queda > 10% em 24h
        else:
            btc = Decimal(80 + (i - 10) * 3)

        eth = Decimal(50 + i)
        btc_points.append(PricePoint(i * day, btc))
        eth_points.append(PricePoint(i * day, eth))

    return {
        "bitcoin": HistoricalSeries("bitcoin", btc_points),
        "ethereum": HistoricalSeries("ethereum", eth_points),
    }


# ---------------------------------------------------------------------------
# RF1 — Carteira protegida
# ---------------------------------------------------------------------------

def demonstrar_rf1(state: DemoState) -> None:
    linha("RF1 — CARTEIRA PROTEGIDA")
    codigo_principal("crypto_portfolio/portfolio.py -> Portfolio.execute_trade")

    if state.portfolio is None:
        saldo = ler_decimal("Saldo inicial em BRL", "50000")
        state.portfolio = Portfolio(
            "BRL", saldo, DEFAULT_ASSET_REGISTRY
        )
        print("  Carteira criada.")
    else:
        print("  Reutilizando a carteira já criada nesta sessão.")

    portfolio = state.portfolio
    mostrar_estado_carteira(portfolio)

    ativo = ler_ativo("bitcoin")
    quantidade = ler_decimal("Quantidade a comprar", "0.1")
    preco = ler_decimal("Preço unitário em USD para a demonstração", "85000")
    fx = ler_decimal("Cotação USD -> BRL", "5.10")

    try:
        trade = portfolio.execute_trade(
            ativo, TradeSide.BUY, quantidade, preco, fx_usd_to_base=fx
        )
        state.last_price_usd = preco
        state.last_fx_usd_to_brl = fx
        print("\n  Compra válida concluída:")
        mostrar_trade(trade)
    except TradingError as e:
        print(f"  Compra recusada: {type(e).__name__}: {e}")

    cash_before = portfolio.cash
    positions_before = portfolio.positions
    held = portfolio.quantity_of(ativo)
    quantidade_invalida = held + Decimal("0.5")

    print(
        f"\n  Agora tentaremos vender {quantidade_invalida} {ativo}, "
        f"mesmo possuindo {held}."
    )
    try:
        portfolio.execute_trade(
            ativo,
            TradeSide.SELL,
            quantidade_invalida,
            preco,
            fx_usd_to_base=fx,
        )
    except TradingError as e:
        print(f"  Operação recusada como esperado: {type(e).__name__}: {e}")

    protegido = (
        portfolio.cash == cash_before
        and portfolio.positions == positions_before
    )
    print(f"\n  Estado permaneceu intocado após a falha? {'SIM' if protegido else 'NÃO'}")
    mostrar_estado_carteira(portfolio)


# ---------------------------------------------------------------------------
# RF2 — Sem mistura implícita de moedas
# ---------------------------------------------------------------------------

def demonstrar_rf2() -> None:
    linha("RF2 — SEM MISTURA IMPLÍCITA DE MOEDAS")
    codigo_principal("crypto_portfolio/money.py -> Amount / CurrencyMismatchError")

    brl = ler_decimal("Valor em BRL", "100")
    usd = ler_decimal("Valor em USD", "20")
    taxa = ler_decimal("Cotação USD -> BRL", "5.00")

    brl_amount = Amount(brl, "BRL")
    usd_amount = Amount(usd, "USD")

    print(f"  Valores criados: {brl_amount} e {usd_amount}")
    print("  Tentando somá-los diretamente...")
    try:
        _ = brl_amount + usd_amount
    except CurrencyMismatchError as e:
        print(f"  Bloqueado como esperado: {type(e).__name__}: {e}")

    convertido = usd_amount.convert_to("BRL", taxa)
    total = brl_amount + convertido
    print(f"\n  Conversão explícita: {usd_amount} -> {convertido}")
    print(f"  Depois da conversão, a soma é permitida: {total}")


# ---------------------------------------------------------------------------
# RF3 — Histórico reprodutível
# ---------------------------------------------------------------------------

def demonstrar_rf3() -> None:
    linha("RF3 — HISTÓRICO REPRODUTÍVEL E IMUTÁVEL")
    codigo_principal(
        "crypto_portfolio/market_data.py -> PricePoint / HistoricalSeries"
    )

    histories = historicos_sinteticos()
    serie = histories["bitcoin"]
    print(f"  Histórico criado com {len(serie)} pontos.")
    print(f"  Primeiro preço: USD {serie.points[0].price_usd}")
    print(f"  Último preço:   USD {serie.points[-1].price_usd}")

    print("\n  Tentando alterar o primeiro preço histórico...")
    try:
        serie.points[0].price_usd = Decimal("999")  # type: ignore[misc]
    except Exception as e:
        print(f"  Alteração bloqueada: {type(e).__name__}")

    print("  Tentando adicionar um novo ponto diretamente...")
    try:
        serie.points.append(PricePoint(999999, Decimal("999")))  # type: ignore[attr-defined]
    except Exception as e:
        print(f"  Alteração bloqueada: {type(e).__name__}")

    tournament = Tournament(DEFAULT_ASSET_REGISTRY, histories)
    primeira = tournament.run(Decimal("10000"))
    segunda = tournament.run(Decimal("10000"))
    r1 = [(r.strategy_name, r.return_pct) for r in primeira]
    r2 = [(r.strategy_name, r.return_pct) for r in segunda]
    print(
        "\n  Mesmo histórico + mesmo capital -> mesmo resultado de backtest? "
        f"{'SIM' if r1 == r2 else 'NÃO'}"
    )


# ---------------------------------------------------------------------------
# RF4 — Tipos de ativos
# ---------------------------------------------------------------------------

def demonstrar_rf4() -> None:
    linha("RF4 — TIPOS DE CRIPTOATIVOS")
    codigo_principal(
        "crypto_portfolio/assets.py -> Asset / Coin / Stablecoin / Token"
    )

    snapshot = snapshot_sintetico()
    exemplos = ("bitcoin", "tether", "dogecoin")

    print("  Mesmo contrato 'risk_score()', implementações diferentes:")
    for asset_id in exemplos:
        asset = DEFAULT_ASSET_REGISTRY[asset_id]
        risco = asset.risk_score(snapshot)
        print(
            f"    {asset_id:10s} -> classe={type(asset).__name__:10s} "
            f"tipo={asset.asset_type.value:10s} risco={risco}"
        )

    print(
        "\n  BTC considera volatilidade; USDT considera desvio de US$ 1; "
        "Token combina volatilidade e penalidade de liquidez/ranking."
    )


# ---------------------------------------------------------------------------
# RF5 — Modelos de risco plugáveis
# ---------------------------------------------------------------------------

def demonstrar_rf5() -> None:
    linha("RF5 — MODELOS DE RISCO PLUGÁVEIS")
    codigo_principal(
        "crypto_portfolio/risk_models.py -> RiskModel / get_risk_model"
    )

    snapshot = snapshot_sintetico()
    portfolio = Portfolio("USD", Decimal("100000"), DEFAULT_ASSET_REGISTRY)
    portfolio.execute_trade(
        "bitcoin", TradeSide.BUY, Decimal("1.05"), snapshot["bitcoin"].price_usd
    )
    portfolio.execute_trade(
        "ethereum", TradeSide.BUY, Decimal("9"), snapshot["ethereum"].price_usd
    )

    escolha = input(
        "Modelo (conservador/agressivo/ambos) [padrão: ambos]: "
    ).strip().lower() or "ambos"
    if escolha not in {"conservador", "agressivo", "ambos"}:
        print("  Opção desconhecida; mostrando ambos.")
        escolha = "ambos"

    nomes = (
        ("conservador", "agressivo") if escolha == "ambos" else (escolha,)
    )

    print("  A MESMA carteira é avaliada pelos modelos selecionados:")
    for nome in nomes:
        model = get_risk_model(nome)
        score, level = model.evaluate(
            portfolio, snapshot, DEFAULT_ASSET_REGISTRY
        )
        print(
            f"    {nome:11s} -> score={score:.2f} | classificação={level.value}"
        )


# ---------------------------------------------------------------------------
# RF6 — Erros de negociação distinguíveis
# ---------------------------------------------------------------------------

def demonstrar_rf6() -> None:
    linha("RF6 — ERROS DE NEGOCIAÇÃO DISTINGUÍVEIS")
    codigo_principal(
        "crypto_portfolio/errors.py + portfolio.py -> exceções específicas"
    )

    portfolio = Portfolio("USD", Decimal("1000"), DEFAULT_ASSET_REGISTRY)

    casos = [
        (
            "Vender BTC sem possuir BTC",
            lambda: portfolio.execute_trade(
                "bitcoin", TradeSide.SELL, Decimal("1"), Decimal("100")
            ),
        ),
        (
            "Negociar ativo inexistente 'dogecoin2'",
            lambda: portfolio.execute_trade(
                "dogecoin2", TradeSide.BUY, Decimal("1"), Decimal("1")
            ),
        ),
        (
            "Comprar acima do saldo disponível",
            lambda: portfolio.execute_trade(
                "ethereum", TradeSide.BUY, Decimal("100"), Decimal("50")
            ),
        ),
        (
            "Usar preço negativo",
            lambda: portfolio.execute_trade(
                "bitcoin", TradeSide.BUY, Decimal("1"), Decimal("-100")
            ),
        ),
    ]

    for descricao, operacao in casos:
        try:
            operacao()
            print(f"  {descricao}: ERRO — operação deveria ter sido recusada")
        except TradingError as e:
            print(f"  {descricao}")
            print(f"    -> {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# RF7 — Trilha de auditoria imutável
# ---------------------------------------------------------------------------

def _garantir_carteira_com_compra(state: DemoState) -> Portfolio:
    if state.portfolio is None:
        state.portfolio = Portfolio(
            "BRL", Decimal("50000"), DEFAULT_ASSET_REGISTRY
        )

    if len(state.portfolio.audit_trail) == 0 or not state.portfolio.positions:
        state.portfolio.execute_trade(
            "bitcoin",
            TradeSide.BUY,
            Decimal("0.1"),
            state.last_price_usd,
            fx_usd_to_base=state.last_fx_usd_to_brl,
        )
    return state.portfolio


def demonstrar_rf7(state: DemoState) -> None:
    linha("RF7 — TRILHA DE AUDITORIA IMUTÁVEL")
    codigo_principal("crypto_portfolio/audit.py -> Trade / AuditTrail")

    portfolio = _garantir_carteira_com_compra(state)

    # Garante que a demonstração tenha BUY e SELL no histórico.
    if portfolio.positions:
        asset_id = next(iter(portfolio.positions))
        held = portfolio.quantity_of(asset_id)
        quantidade_venda = held / Decimal("2")
        if quantidade_venda > 0:
            portfolio.execute_trade(
                asset_id,
                TradeSide.SELL,
                quantidade_venda,
                state.last_price_usd + Decimal("500"),
                fx_usd_to_base=state.last_fx_usd_to_brl,
            )

    print("  Negociações concluídas registradas:")
    for trade in portfolio.audit_trail.entries:
        mostrar_trade(trade)

    entries = portfolio.audit_trail.entries
    if entries:
        print("\n  Tentando alterar uma negociação já registrada...")
        try:
            entries[0].quantity = Decimal("999")  # type: ignore[misc]
        except (FrozenInstanceError, AttributeError) as e:
            print(f"  Alteração bloqueada: {type(e).__name__}")

    print(
        "  AuditTrail possui método remove? "
        f"{'SIM' if hasattr(portfolio.audit_trail, 'remove') else 'NÃO'}"
    )
    print(
        "  AuditTrail possui método clear?  "
        f"{'SIM' if hasattr(portfolio.audit_trail, 'clear') else 'NÃO'}"
    )


# ---------------------------------------------------------------------------
# RF8 — Preços cientes de limite de requisições
# ---------------------------------------------------------------------------

def demonstrar_rf8(price_service: PriceService) -> None:
    linha("RF8 — PREÇOS CIENTES DE LIMITE DE REQUISIÇÕES")
    codigo_principal(
        "crypto_portfolio/market_data.py -> PriceService / TokenBucketRateLimiter / _retrying_get"
    )

    print("  Esta é a única demonstração que precisa da CoinGecko ao vivo.")
    print("  Primeira consulta em lote para BTC, ETH e USDT...")
    primeira = price_service.get_prices(COIN_IDS)

    for cid in COIN_IDS:
        point = primeira.get(cid)
        if point:
            print(
                f"    {cid:10s} USD={point.price_usd} BRL={point.price_brl} "
                f"24h={point.change_24h_pct}%"
            )

    print("\n  Repetindo imediatamente a MESMA consulta...")
    segunda = price_service.get_prices(COIN_IDS)
    reutilizou = all(
        cid in primeira
        and cid in segunda
        and primeira[cid] is segunda[cid]
        for cid in COIN_IDS
    )
    print(
        "  Os mesmos objetos em cache foram reutilizados? "
        f"{'SIM' if reutilizou else 'NÃO'}"
    )
    print(
        "  Se a CoinGecko responder HTTP 429, _retrying_get respeita Retry-After "
        "ou aplica backoff antes de tentar novamente."
    )


# ---------------------------------------------------------------------------
# RF9 — Conjunto aberto de estratégias
# ---------------------------------------------------------------------------

def demonstrar_rf9() -> None:
    linha("RF9 — CONJUNTO ABERTO DE ESTRATÉGIAS")
    codigo_principal(
        "crypto_portfolio/strategies.py -> Strategy / @register_strategy / available_strategies"
    )

    snapshot = {
        "bitcoin": MarketPoint(Decimal("100"), Decimal("500"), Decimal("-12"), 1),
        "ethereum": MarketPoint(Decimal("50"), Decimal("250"), Decimal("2"), 2),
    }
    portfolio = Portfolio("USD", Decimal("10000"), DEFAULT_ASSET_REGISTRY)
    portfolio.execute_trade("bitcoin", TradeSide.BUY, Decimal("20"), Decimal("100"))
    portfolio.execute_trade("ethereum", TradeSide.BUY, Decimal("40"), Decimal("50"))

    strategies = available_strategies()
    print(f"  Estratégias registradas automaticamente: {list(strategies.keys())}")

    for nome, strategy_cls in strategies.items():
        strategy = strategy_cls()
        recs = strategy.evaluate(
            portfolio, snapshot, DEFAULT_ASSET_REGISTRY, {"timestamp": 0}
        )
        print(f"\n  {nome}:")
        for rec in recs:
            print(
                f"    {rec.action.value:7s} {rec.asset_id:10s} "
                f"qtd={rec.quantity} | {rec.reason}"
            )

    print(
        "\n  STOP-LOSS aparece sem o Tournament conhecer essa classe diretamente; "
        "ele entra pelo registro de estratégias."
    )


# ---------------------------------------------------------------------------
# RF10 — Torneio de estratégias
# ---------------------------------------------------------------------------

def demonstrar_rf10() -> None:
    linha("RF10 — TORNEIO DE ESTRATÉGIAS")
    codigo_principal("crypto_portfolio/tournament.py -> Tournament.run")

    capital = ler_decimal("Capital inicial do backtest em USD", "10000")
    histories = historicos_sinteticos()
    tournament = Tournament(DEFAULT_ASSET_REGISTRY, histories)
    ranking = tournament.run(capital)

    print(
        "  Todas as estratégias recebem o MESMO histórico e a MESMA condição inicial."
    )
    print("  Classificação:")
    for pos, result in enumerate(ranking, start=1):
        print(
            f"    {pos}º {result.strategy_name:16s} "
            f"inicial=USD {result.initial_value_usd:.2f} "
            f"final=USD {result.final_value_usd:.2f} "
            f"retorno={result.return_pct:+.2f}%"
        )

    nomes_registrados = set(available_strategies().keys())
    nomes_torneio = {r.strategy_name for r in ranking}
    print(
        "\n  Todas as estratégias registradas participaram? "
        f"{'SIM' if nomes_registrados == nomes_torneio else 'NÃO'}"
    )


# ---------------------------------------------------------------------------
# Menu principal
# ---------------------------------------------------------------------------

def mostrar_menu() -> None:
    print("\n" + "=" * 78)
    print(" CRYPTO PORTFOLIO — DEMONSTRAÇÃO POR REQUISITO FUNCIONAL")
    print("=" * 78)
    print("  1. RF1  — Carteira protegida")
    print("  2. RF2  — Sem mistura implícita de moedas")
    print("  3. RF3  — Histórico reprodutível")
    print("  4. RF4  — Tipos de criptoativos")
    print("  5. RF5  — Modelos de risco plugáveis")
    print("  6. RF6  — Erros de negociação distinguíveis")
    print("  7. RF7  — Trilha de auditoria imutável")
    print("  8. RF8  — Preços cientes de limite de requisições")
    print("  9. RF9  — Conjunto aberto de estratégias")
    print(" 10. RF10 — Torneio de estratégias")
    print("  0. Sair")
    print("=" * 78)


def main() -> None:
    state = DemoState()
    # Uma única instância durante a sessão: o cache do RF8 pode ser reaproveitado.
    price_service = PriceService(cache_ttl=30.0, max_calls_per_minute=10)

    acoes = {
        "1": lambda: demonstrar_rf1(state),
        "2": demonstrar_rf2,
        "3": demonstrar_rf3,
        "4": demonstrar_rf4,
        "5": demonstrar_rf5,
        "6": demonstrar_rf6,
        "7": lambda: demonstrar_rf7(state),
        "8": lambda: demonstrar_rf8(price_service),
        "9": demonstrar_rf9,
        "10": demonstrar_rf10,
    }

    while True:
        mostrar_menu()
        opcao = input("Escolha o RF que deseja demonstrar: ").strip()

        if opcao == "0":
            print("\nPrograma encerrado.")
            break

        acao = acoes.get(opcao)
        if acao is None:
            print("\nOpção inválida. Digite um número de 0 a 10.")
            continue

        try:
            acao()
        except (TradingError, requests.RequestException) as e:
            print(
                f"\nNão foi possível concluir esta demonstração: "
                f"{type(e).__name__}: {e}"
            )

        input("\nPressione Enter para voltar ao menu de RFs...")


if __name__ == "__main__":
    main()
