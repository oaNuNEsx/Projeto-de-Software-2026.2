"""
strategies.py
-------------
RF9 — Conjunto aberto de estratégias.

`Strategy` é a interface: qualquer classe que a implemente e seja
decorada com `@register_strategy` passa a existir automaticamente para
o torneio (RF10) — sem editar HODL, DCA, Rebalanceamento nem o próprio
`Tournament`. `StopLossStrategy`, ao final do arquivo, é o exemplo desse
"acréscimo na semana 7": ela não toca em nenhuma das outras.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Dict, List


class Action(Enum):
    HOLD = "MANTER"
    BUY = "COMPRAR"
    SELL = "VENDER"


@dataclass(frozen=True)
class Recommendation:
    strategy_name: str
    action: Action
    asset_id: str
    quantity: Decimal
    reason: str


class Strategy(ABC):
    name: str

    @abstractmethod
    def evaluate(self, portfolio, market_snapshot, asset_registry, context: dict) -> List[Recommendation]:
        """Analisa a carteira/mercado atuais e devolve uma lista de recomendações."""


_STRATEGY_REGISTRY: Dict[str, type] = {}


def register_strategy(cls):
    """Decorator: registra a estratégia para aparecer automaticamente no torneio."""
    _STRATEGY_REGISTRY[cls.name] = cls
    return cls


def available_strategies() -> Dict[str, type]:
    """Devolve uma cópia do registro — o torneio não precisa saber quantas existem."""
    return dict(_STRATEGY_REGISTRY)


# ------------------------------------------------------------------ #
# Estratégias base (semana 1)
# ------------------------------------------------------------------ #

@register_strategy
class HodlStrategy(Strategy):
    name = "HODL"

    def evaluate(self, portfolio, market_snapshot, asset_registry, context):
        return [Recommendation(self.name, Action.HOLD, "-", Decimal("0"),
                                "HODL nunca opera: manter todas as posições atuais.")]


@register_strategy
class DcaStrategy(Strategy):
    name = "DCA"

    def __init__(self, target_asset: str = "bitcoin", amount_per_cycle: Decimal = Decimal("50")):
        self.target_asset = target_asset
        self.amount_per_cycle = Decimal(str(amount_per_cycle))

    def evaluate(self, portfolio, market_snapshot, asset_registry, context):
        point = market_snapshot.get(self.target_asset)
        if not point or point.price_usd == 0:
            return [Recommendation(self.name, Action.HOLD, self.target_asset, Decimal("0"),
                                    "Sem preço disponível neste ciclo; aguardando o próximo.")]
        qty = (self.amount_per_cycle / point.price_usd).quantize(Decimal("0.00000001"))
        return [Recommendation(
            self.name, Action.BUY, self.target_asset, qty,
            f"Aporte fixo de {self.amount_per_cycle} independente do preço atual."
        )]


@register_strategy
class RebalanceStrategy(Strategy):
    name = "REBALANCEAMENTO"

    def __init__(self, target_weights: Dict[str, Decimal] | None = None, tolerance: Decimal = Decimal("0.05")):
        self.target_weights = target_weights or {"bitcoin": Decimal("0.6"), "ethereum": Decimal("0.4")}
        self.tolerance = Decimal(str(tolerance))

    def evaluate(self, portfolio, market_snapshot, asset_registry, context):
        total = portfolio.total_value_usd(market_snapshot).value + portfolio.cash.value
        if total == 0:
            return [Recommendation(self.name, Action.HOLD, "-", Decimal("0"), "Carteira vazia.")]

        recs = []
        for asset_id, target_w in self.target_weights.items():
            point = market_snapshot.get(asset_id)
            if not point or point.price_usd == 0:
                continue
            qty_held = portfolio.quantity_of(asset_id)
            current_value = qty_held * point.price_usd
            current_w = current_value / total
            diff_w = target_w - current_w
            if abs(diff_w) <= self.tolerance:
                continue
            diff_value = diff_w * total
            qty_diff = (diff_value / point.price_usd).quantize(Decimal("0.00000001"))
            if qty_diff > 0:
                recs.append(Recommendation(
                    self.name, Action.BUY, asset_id, qty_diff,
                    f"Peso atual {current_w:.2%} abaixo do alvo {target_w:.0%}."
                ))
            elif qty_diff < 0:
                recs.append(Recommendation(
                    self.name, Action.SELL, asset_id, abs(qty_diff),
                    f"Peso atual {current_w:.2%} acima do alvo {target_w:.0%}."
                ))
        if not recs:
            recs.append(Recommendation(self.name, Action.HOLD, "-", Decimal("0"), "Carteira já balanceada."))
        return recs


# ------------------------------------------------------------------ #
# "Semana 7": nova estratégia, ZERO edições nas anteriores (RF9/RF10)
# ------------------------------------------------------------------ #

@register_strategy
class StopLossStrategy(Strategy):
    name = "STOP-LOSS"

    def __init__(self, drop_threshold_pct: Decimal = Decimal("10")):
        self.drop_threshold_pct = Decimal(str(drop_threshold_pct))

    def evaluate(self, portfolio, market_snapshot, asset_registry, context):
        recs = []
        for asset_id, qty in portfolio.positions.items():
            point = market_snapshot.get(asset_id)
            if not point:
                continue
            if point.change_24h_pct <= -self.drop_threshold_pct:
                recs.append(Recommendation(
                    self.name, Action.SELL, asset_id, qty,
                    f"Queda de {point.change_24h_pct}% em 24h ultrapassa o limite de "
                    f"-{self.drop_threshold_pct}%; vendendo para conter perdas."
                ))
        if not recs:
            recs.append(Recommendation(self.name, Action.HOLD, "-", Decimal("0"),
                                        "Nenhum ativo ultrapassou o limite de queda."))
        return recs
