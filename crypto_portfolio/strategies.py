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


# ------------------------------------------------------------------ #
# Padrão Decorator (estrutural): envoltórios para Strategy
# ------------------------------------------------------------------ #

from .assets import Asset


class StrategyDecorator(Strategy):
    """
    Decorator base abstrato para estratégias (Padrão Decorator).

    Envolve uma instância de `Strategy` e repassa chamadas a ela por padrão.
    Subclasses concretas podem estender ou modificar o comportamento de
    `evaluate` antes ou depois da delegação à estratégia envolvida.
    """

    def __init__(self, wrapped: Strategy) -> None:
        self._wrapped = wrapped

    @property
    def name(self) -> str:
        """Delega o nome à estratégia envelopada."""
        return self._wrapped.name

    def evaluate(
        self, portfolio, market_snapshot, asset_registry: Dict[str, Asset] | None, context: dict | None = None
    ) -> List[Recommendation]:
        """Delega a avaliação de mercado à estratégia envelopada por padrão."""
        return self._wrapped.evaluate(
            portfolio, market_snapshot, asset_registry, context if context is not None else {}
        )


class LoggingDecorator(StrategyDecorator):
    """
    Decorator que registra em log todas as recomendações emitidas pela estratégia.

    Acumula mensagens formatadas internamente e oferece acesso somente-leitura
    por meio de uma tupla imutável (cópia defensiva), além de método para limpeza.
    """

    def __init__(self, wrapped: Strategy) -> None:
        super().__init__(wrapped)
        self._log: list[str] = []

    @property
    def log(self) -> tuple[str, ...]:
        """Devolve uma cópia imutável (tupla) do histórico de logs."""
        return tuple(self._log)

    def limpar_log(self) -> None:
        """Limpa todo o histórico de logs acumulado."""
        self._log.clear()

    def evaluate(
        self, portfolio, market_snapshot, asset_registry: Dict[str, Asset] | None, context: dict | None = None
    ) -> List[Recommendation]:
        """Executa a estratégia envelopada e registra cada recomendação no log."""
        recs = self._wrapped.evaluate(
            portfolio, market_snapshot, asset_registry, context if context is not None else {}
        )
        for rec in recs:
            msg = f"[{rec.strategy_name}] {rec.action.value} {rec.asset_id} qtd={rec.quantity} | {rec.reason}"
            self._log.append(msg)
        return recs


class RiskLimitDecorator(StrategyDecorator):
    """
    Decorator que filtra recomendações de compra caso o risco do ativo exceda o limite.

    Ordens de COMPRA (BUY) para ativos cujo `risk_score(market_snapshot)` seja superior
    a `max_risk` são convertidas em MANTER (HOLD), justificando o bloqueio.
    Ordens de MANTER (HOLD) e VENDER (SELL) passam inalteradas.
    """

    def __init__(self, wrapped: Strategy, max_risk: Decimal = Decimal("50")) -> None:
        super().__init__(wrapped)
        self.max_risk = Decimal(str(max_risk))

    def evaluate(
        self, portfolio, market_snapshot, asset_registry: Dict[str, Asset] | None, context: dict | None = None
    ) -> List[Recommendation]:
        """Executa a avaliação e bloqueia compras de ativos que ultrapassam max_risk."""
        recs = self._wrapped.evaluate(
            portfolio, market_snapshot, asset_registry, context if context is not None else {}
        )
        filtered: list[Recommendation] = []
        for rec in recs:
            if rec.action == Action.BUY:
                asset = asset_registry.get(rec.asset_id) if asset_registry else None
                if asset is not None:
                    risk = asset.risk_score(market_snapshot)
                    if risk > self.max_risk:
                        filtered.append(
                            Recommendation(
                                strategy_name=rec.strategy_name,
                                action=Action.HOLD,
                                asset_id=rec.asset_id,
                                quantity=Decimal("0"),
                                reason=(
                                    f"Compra bloqueada por limite de risco: score de risco ({risk}) "
                                    f"excede o máximo permitido ({self.max_risk})."
                                ),
                            )
                        )
                        continue
            filtered.append(rec)
        return filtered
