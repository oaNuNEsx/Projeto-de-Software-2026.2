"""
tournament.py
-------------
RF10 — Torneio de estratégias.

Todas as estratégias rodam sobre o mesmo histórico e começam da mesma
carteira inicial. Por padrão, 35% do capital é colocado em BTC, 35% em ETH
e 30% permanece em caixa. Isso permite comparar HODL, DCA,
Rebalanceamento e Stop-Loss em uma condição inicial comum.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from .assets import Asset
from .audit import TradeSide
from .errors import TradingError
from .portfolio import Portfolio
from .portfolio_builder import PortfolioBuilder
from .strategies import available_strategies, Action
from .market_data import HistoricalSeries, MarketPoint

DAY_MS = 86_400_000


@dataclass
class BacktestResult:
    strategy_name: str
    initial_value_usd: Decimal
    final_value_usd: Decimal

    @property
    def return_pct(self) -> Decimal:
        if self.initial_value_usd == 0:
            return Decimal("0")
        return ((self.final_value_usd - self.initial_value_usd) / self.initial_value_usd) * 100


class Tournament:
    def __init__(self, asset_registry: Dict[str, Asset], histories: Dict[str, HistoricalSeries],
                 initial_weights: Dict[str, Decimal] | None = None):
        self.asset_registry = asset_registry
        self.histories = histories
        self.initial_weights = initial_weights or {
            "bitcoin": Decimal("0.35"),
            "ethereum": Decimal("0.35"),
        }

        PortfolioBuilder.validar_pesos(self.initial_weights)

    def _snapshot_at(self, timestamp_ms: int) -> Dict[str, MarketPoint]:
        snapshot: Dict[str, MarketPoint] = {}
        for asset_id, series in self.histories.items():
            point = series.price_at_or_before(timestamp_ms)
            if point is None:
                continue

            previous = series.price_at_or_before(timestamp_ms - DAY_MS)
            if previous is None or previous.price_usd == 0:
                change_24h_pct = Decimal("0")
            else:
                change_24h_pct = (
                    (point.price_usd - previous.price_usd) / previous.price_usd
                ) * Decimal("100")

            snapshot[asset_id] = MarketPoint(
                price_usd=point.price_usd,
                price_brl=Decimal("0"),
                change_24h_pct=change_24h_pct,
                market_cap_rank=1,
            )
        return snapshot

    def _montar_carteira_inicial(self, base_currency: str, initial_cash_usd: Decimal,
                                 snapshot: Dict[str, MarketPoint]) -> Portfolio:
        """Builder: monta a carteira inicial (caixa + compras por peso) em etapas nomeadas."""
        builder = (PortfolioBuilder(self.asset_registry)
                   .com_moeda_base(base_currency)
                   .com_caixa_inicial(initial_cash_usd)
                   .com_precos(snapshot))
        for asset_id, weight in self.initial_weights.items():
            builder.com_posicao_por_peso(asset_id, weight)
        return builder.build()

    def run(self, initial_cash_usd: Decimal, base_currency: str = "USD",
             step_points: int = 1) -> List[BacktestResult]:
        if not self.histories:
            return []

        reference_series = max(self.histories.values(), key=len)
        timestamps = [p.timestamp for p in reference_series.points][::step_points]
        if not timestamps:
            return []

        results: List[BacktestResult] = []
        initial_snapshot = self._snapshot_at(timestamps[0])

        # Builder monta a carteira inicial UMA vez; Prototype dá um clone a cada estratégia,
        # então todas partem exatamente do mesmo estado (RF10) por construção.
        carteira_inicial = self._montar_carteira_inicial(base_currency, initial_cash_usd, initial_snapshot)
        initial_value = carteira_inicial.total_value_usd(initial_snapshot).value + carteira_inicial.cash.value

        for name, strategy_cls in available_strategies().items():
            strategy = strategy_cls()
            portfolio = carteira_inicial.clonar()

            for ts in timestamps:
                snapshot = self._snapshot_at(ts)
                if not snapshot:
                    continue
                recs = strategy.evaluate(portfolio, snapshot, self.asset_registry, {"timestamp": ts})
                for rec in recs:
                    if rec.action == Action.HOLD or rec.quantity == 0:
                        continue
                    point = snapshot.get(rec.asset_id)
                    if not point or point.price_usd <= 0:
                        continue
                    side = TradeSide.BUY if rec.action == Action.BUY else TradeSide.SELL
                    try:
                        portfolio.execute_trade(
                            rec.asset_id, side, rec.quantity, point.price_usd,
                            fx_usd_to_base=Decimal("1")
                        )
                    except TradingError:
                        # Recomendação inviável no momento (sem caixa/posição).
                        continue

            final_snapshot = self._snapshot_at(timestamps[-1])
            final_value = portfolio.total_value_usd(final_snapshot).value + portfolio.cash.value
            results.append(BacktestResult(name, initial_value, final_value))

        return sorted(results, key=lambda r: r.return_pct, reverse=True)