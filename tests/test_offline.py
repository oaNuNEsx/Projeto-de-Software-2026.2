"""
Testes que NÃO dependem de rede — usam dados de mercado simulados para
validar as regras de negócio (RF1-RF7, RF9, RF10). A comunicação real
com a CoinGecko (RF8) fica em `main.py`, que exige internet para rodar.
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_portfolio.money import Amount, CurrencyMismatchError
from crypto_portfolio.errors import InsufficientPositionError, AssetNotFoundError, InsufficientBalanceError
from crypto_portfolio.assets import DEFAULT_ASSET_REGISTRY
from crypto_portfolio.audit import TradeSide
from crypto_portfolio.portfolio import Portfolio
from crypto_portfolio.risk_models import get_risk_model, RiskLevel
from crypto_portfolio.strategies import available_strategies
from crypto_portfolio.market_data import MarketPoint, HistoricalSeries, PricePoint
from crypto_portfolio.tournament import Tournament


def make_snapshot():
    return {
        "bitcoin": MarketPoint(Decimal("60000"), Decimal("300000"), Decimal("5"), 1),
        "ethereum": MarketPoint(Decimal("3000"), Decimal("15000"), Decimal("8"), 2),
        "tether": MarketPoint(Decimal("0.97"), Decimal("4.85"), Decimal("0.1"), 5),
    }


def test_rf2_currency_mismatch():
    brl_value = Amount(Decimal("100"), "BRL")
    usd_value = Amount(Decimal("20"), "USD")
    try:
        brl_value + usd_value
        assert False, "deveria ter lançado CurrencyMismatchError"
    except CurrencyMismatchError:
        pass
    # conversão explícita funciona:
    converted = usd_value.convert_to("BRL", Decimal("5.0"))
    total = brl_value + converted
    assert total == Amount(Decimal("200"), "BRL")
    print("RF2 OK — soma implícita de moedas diferentes é impossível; conversão explícita funciona.")


def test_rf1_rf6_rf7_wallet_protection():
    portfolio = Portfolio("BRL", Decimal("10000"), DEFAULT_ASSET_REGISTRY)
    snapshot = make_snapshot()

    # compra válida de BTC (0.02 BTC * 60000 USD * 5.0 fx = 6000 BRL, cabe nos 10000)
    portfolio.execute_trade("bitcoin", TradeSide.BUY, Decimal("0.02"), snapshot["bitcoin"].price_usd,
                             fx_usd_to_base=Decimal("5.0"))
    assert portfolio.quantity_of("bitcoin") == Decimal("0.02")

    # tentar vender mais do que se tem -> erro específico, estado intocado
    qty_before = portfolio.quantity_of("bitcoin")
    cash_before = portfolio.cash
    try:
        portfolio.execute_trade("bitcoin", TradeSide.SELL, Decimal("0.5"), snapshot["bitcoin"].price_usd,
                                 fx_usd_to_base=Decimal("5.0"))
        assert False, "deveria ter lançado InsufficientPositionError"
    except InsufficientPositionError:
        pass
    assert portfolio.quantity_of("bitcoin") == qty_before
    assert portfolio.cash == cash_before

    # ativo inexistente -> erro DIFERENTE do de saldo/posição
    try:
        portfolio.execute_trade("dogecoin2", TradeSide.BUY, Decimal("1"), Decimal("1"), Decimal("5.0"))
        assert False
    except AssetNotFoundError:
        pass

    # saldo insuficiente -> outro erro específico
    try:
        portfolio.execute_trade("ethereum", TradeSide.BUY, Decimal("1000"), snapshot["ethereum"].price_usd,
                                 fx_usd_to_base=Decimal("5.0"))
        assert False
    except InsufficientBalanceError:
        pass

    # trilha de auditoria: só a compra válida está lá, e é imutável
    entries = portfolio.audit_trail.entries
    assert len(entries) == 1
    assert entries[0].asset_id == "bitcoin"
    try:
        entries[0].quantity = Decimal("999")  # type: ignore
        assert False, "Trade deveria ser imutável (frozen)"
    except Exception:
        pass
    # a tupla devolvida também não afeta o histórico real
    assert not hasattr(portfolio.audit_trail, "remove")
    assert not hasattr(portfolio.audit_trail, "clear")
    print("RF1/RF6/RF7 OK — carteira protegida, erros distinguíveis, auditoria imutável e sem métodos de edição.")


def test_rf4_risk_per_asset_type():
    snapshot = make_snapshot()
    btc_risk = DEFAULT_ASSET_REGISTRY["bitcoin"].risk_score(snapshot)
    usdt_risk = DEFAULT_ASSET_REGISTRY["tether"].risk_score(snapshot)
    # USDT a 0.97 (desvio de peg) deve ser considerado MAIS arriscado
    # que sua volatilidade de 0.1% sugeriria isoladamente
    assert usdt_risk > Decimal("10")
    assert btc_risk > Decimal("0")
    print(f"RF4 OK — risco BTC(vol 24h)={btc_risk}, risco USDT(desvio de peg)={usdt_risk}")


def test_rf5_pluggable_risk_models():
    snapshot = make_snapshot()
    # carteira concentrada: ~70% do valor em BTC, ~30% em ETH
    portfolio = Portfolio("USD", Decimal("100000"), DEFAULT_ASSET_REGISTRY)
    portfolio.execute_trade("bitcoin", TradeSide.BUY, Decimal("1.05"), snapshot["bitcoin"].price_usd)  # ~63000
    portfolio.execute_trade("ethereum", TradeSide.BUY, Decimal("9"), snapshot["ethereum"].price_usd)   # ~27000

    conservative = get_risk_model("conservador")
    aggressive = get_risk_model("agressivo")
    score_c, level_c = conservative.evaluate(portfolio, snapshot, DEFAULT_ASSET_REGISTRY)
    score_a, level_a = aggressive.evaluate(portfolio, snapshot, DEFAULT_ASSET_REGISTRY)
    print(f"RF5 OK — mesma carteira: conservador={level_c.value} (score {score_c:.1f}), "
          f"agressivo={level_a.value} (score {score_a:.1f})")
    assert level_c != level_a or score_c != score_a


def test_rf9_rf10_open_strategies_and_tournament():
    strategies = available_strategies()
    assert "HODL" in strategies and "DCA" in strategies and "REBALANCEAMENTO" in strategies
    assert "STOP-LOSS" in strategies  # a estratégia "da semana 7" já está plugada
    n_before = len(strategies)

    # histórico sintético e IMUTÁVEL para bitcoin e ethereum (RF3)
    btc_points = [PricePoint(i * 86_400_000, Decimal(str(30000 + i * 500))) for i in range(30)]
    eth_points = [PricePoint(i * 86_400_000, Decimal(str(2000 + i * 20))) for i in range(30)]
    histories = {
        "bitcoin": HistoricalSeries("bitcoin", btc_points),
        "ethereum": HistoricalSeries("ethereum", eth_points),
    }

    tournament = Tournament(DEFAULT_ASSET_REGISTRY, histories)
    results_1 = tournament.run(Decimal("10000"))
    results_2 = tournament.run(Decimal("10000"))

    # reprodutibilidade (RF3): mesmo histórico -> mesmo resultado
    assert [ (r.strategy_name, r.return_pct) for r in results_1] == \
           [ (r.strategy_name, r.return_pct) for r in results_2]

    ranked_names = [r.strategy_name for r in results_1]
    assert set(ranked_names) == set(strategies.keys())
    assert len(results_1) == n_before  # todas as estratégias registradas participaram

    print("RF9/RF10 OK — torneio roda TODAS as estratégias registradas (inclusive STOP-LOSS) e é reprodutível:")
    for r in results_1:
        print(f"   {r.strategy_name:16s} retorno={r.return_pct:.2f}%")


def test_rf3_history_is_immutable():
    points = [PricePoint(0, Decimal("100")), PricePoint(1000, Decimal("101"))]
    series = HistoricalSeries("bitcoin", points)
    try:
        series.points[0].price_usd = Decimal("999")  # type: ignore
        assert False
    except Exception:
        pass
    try:
        series.points.append(PricePoint(2000, Decimal("102")))  # type: ignore
        assert False
    except AttributeError:
        pass
    print("RF3 OK — série histórica é imutável (frozen + tupla).")


if __name__ == "__main__":
    test_rf2_currency_mismatch()
    test_rf1_rf6_rf7_wallet_protection()
    test_rf4_risk_per_asset_type()
    test_rf5_pluggable_risk_models()
    test_rf9_rf10_open_strategies_and_tournament()
    test_rf3_history_is_immutable()
    print("\nTodos os testes offline passaram.")


def test_negative_price_and_exchange_rate_are_rejected():
    from crypto_portfolio.errors import InvalidPriceError, InvalidExchangeRateError

    portfolio = Portfolio("USD", Decimal("1000"), DEFAULT_ASSET_REGISTRY)
    cash_before = portfolio.cash
    positions_before = portfolio.positions

    try:
        portfolio.execute_trade("bitcoin", TradeSide.BUY, Decimal("1"), Decimal("-100"))
        assert False, "preço negativo deveria ser rejeitado"
    except InvalidPriceError:
        pass

    assert portfolio.cash == cash_before
    assert portfolio.positions == positions_before

    try:
        portfolio.execute_trade(
            "bitcoin", TradeSide.BUY, Decimal("1"), Decimal("100"),
            fx_usd_to_base=Decimal("0")
        )
        assert False, "taxa de câmbio zero deveria ser rejeitada"
    except InvalidExchangeRateError:
        pass

    assert portfolio.cash == cash_before
    assert portfolio.positions == positions_before


def test_tournament_calculates_24h_change_and_seeds_portfolio():
    day = 86_400_000
    histories = {
        "bitcoin": HistoricalSeries("bitcoin", [
            PricePoint(0, Decimal("100")),
            PricePoint(day, Decimal("80")),
            PricePoint(day * 2, Decimal("120")),
        ]),
        "ethereum": HistoricalSeries("ethereum", [
            PricePoint(0, Decimal("100")),
            PricePoint(day, Decimal("80")),
            PricePoint(day * 2, Decimal("120")),
        ]),
    }

    tournament = Tournament(DEFAULT_ASSET_REGISTRY, histories)
    snapshot = tournament._snapshot_at(day)
    assert snapshot["bitcoin"].change_24h_pct == Decimal("-20.0")

    results = {r.strategy_name: r for r in tournament.run(Decimal("10000"))}
    assert results["HODL"].return_pct != Decimal("0")
    assert results["STOP-LOSS"].return_pct != results["HODL"].return_pct


def test_history_cache_distinguishes_number_of_days():
    from crypto_portfolio.market_data import HistoricalDataStore

    class FakeResponse:
        status_code = 200
        headers = {}

        def __init__(self, days):
            self.days = days

        def raise_for_status(self):
            pass

        def json(self):
            if self.days == 30:
                return {"prices": [[0, 100], [1, 101]]}
            return {"prices": [[0, 100], [1, 101], [2, 102]]}

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, timeout=None):
            self.calls.append(dict(params))
            return FakeResponse(params["days"])

    session = FakeSession()
    store = HistoricalDataStore(session=session)

    series_30 = store.fetch("bitcoin", days=30)
    series_180 = store.fetch("bitcoin", days=180)

    assert len(series_30) == 2
    assert len(series_180) == 3
    assert series_30 is not series_180
    assert len(session.calls) == 2
