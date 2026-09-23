"""
main.py
-------
Demonstração ponta a ponta usando a API da CoinGecko.
Requer conexão com a internet para rodar (acessa api.coingecko.com).

Executa:
  1. Busca preços atuais de BTC, ETH e USDT (RF8: uma única chamada em lote).
  2. Cria uma carteira e faz algumas negociações, incluindo uma inválida
     de propósito, para mostrar RF1/RF6/RF7.
  3. Calcula o risco da carteira sob dois modelos diferentes (RF5).
  4. Busca histórico de preços (RF3) e roda um torneio de estratégias (RF9/RF10).
"""
from decimal import Decimal

from crypto_portfolio.assets import DEFAULT_ASSET_REGISTRY
from crypto_portfolio.audit import TradeSide
from crypto_portfolio.errors import TradingError
from crypto_portfolio.market_data import PriceService, HistoricalDataStore
from crypto_portfolio.portfolio import Portfolio
from crypto_portfolio.risk_models import get_risk_model
from crypto_portfolio.strategies import available_strategies
from crypto_portfolio.tournament import Tournament


def linha(titulo: str) -> None:
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def main():
    price_service = PriceService(cache_ttl=30.0, max_calls_per_minute=10)
    coin_ids = ["bitcoin", "ethereum", "tether"]

    linha("1) Preços atuais (RF8 — uma única chamada para todas as moedas)")
    snapshot = price_service.get_prices(coin_ids)
    for cid, point in snapshot.items():
        print(f"  {cid:10s} USD={point.price_usd:>12} BRL={point.price_brl:>12} "
              f"24h={point.change_24h_pct:>6}% rank={point.market_cap_rank}")

    # taxa USD->BRL só para exemplificar a conversão EXPLÍCITA (RF2)
    usdbrl = (snapshot["bitcoin"].price_brl / snapshot["bitcoin"].price_usd) if snapshot["bitcoin"].price_usd else Decimal("5")

    linha("2) Carteira protegida (RF1), erros distinguíveis (RF6), auditoria (RF7)")
    portfolio = Portfolio(base_currency="BRL", initial_cash=Decimal("50000"),
                           asset_registry=DEFAULT_ASSET_REGISTRY)

    portfolio.execute_trade("bitcoin", TradeSide.BUY, Decimal("0.1"),
                             snapshot["bitcoin"].price_usd, fx_usd_to_base=usdbrl)
    print(f"  Comprou 0.1 BTC. Caixa restante: {portfolio.cash}")

    try:
        # Vender mais BTC do que se possui -> deve falhar sem tocar no estado
        portfolio.execute_trade("bitcoin", TradeSide.SELL, Decimal("0.5"),
                                 snapshot["bitcoin"].price_usd, fx_usd_to_base=usdbrl)
    except TradingError as e:
        print(f"  Negociação recusada (esperado): {type(e).__name__}: {e}")

    try:
        # Ativo inexistente -> erro DIFERENTE do de cima
        portfolio.execute_trade("dogecoin2", TradeSide.BUY, Decimal("10"), Decimal("1"), Decimal("5"))
    except TradingError as e:
        print(f"  Negociação recusada (esperado): {type(e).__name__}: {e}")

    print(f"  Posição final em BTC: {portfolio.quantity_of('bitcoin')} (não foi afetada pelas falhas)")
    print("  Trilha de auditoria:")
    for t in portfolio.audit_trail.entries:
        print(f"    {t.trade_id} {t.side.value:4s} {t.quantity} {t.asset_id} a {t.price_usd} USD")

    linha("3) Risco sob modelos plugáveis (RF5)")
    for model_name in ("conservador", "agressivo"):
        model = get_risk_model(model_name)
        score, level = model.evaluate(portfolio, snapshot, DEFAULT_ASSET_REGISTRY)
        print(f"  Modelo '{model_name}': score={score:.1f} -> classificação = {level.value}")

    linha("4) Histórico imutável (RF3) + Torneio de estratégias (RF9/RF10)")
    print(f"  Estratégias atualmente registradas: {list(available_strategies().keys())}")
    history_store = HistoricalDataStore()
    histories = {cid: history_store.fetch(cid, days=180) for cid in ("bitcoin", "ethereum")}
    for cid, series in histories.items():
        print(f"  Histórico de {cid}: {len(series)} pontos (imutável após obtido)")

    tournament = Tournament(DEFAULT_ASSET_REGISTRY, histories)
    ranking = tournament.run(initial_cash_usd=Decimal("10000"))
    print("\n  Classificação do backtest (últimos 180 dias):")
    for pos, result in enumerate(ranking, start=1):
        print(f"    {pos}º {result.strategy_name:16s} retorno={result.return_pct:+.2f}%")


if __name__ == "__main__":
    main()
