"""
risk_models.py
--------------
RF5 — Modelos de risco plugáveis.

`RiskModel` é uma interface (ABC). Qualquer novo modelo só precisa
implementar `score_portfolio` e `classify` e se registrar em
`RISK_MODEL_REGISTRY` — nada mais no sistema precisa mudar.

Dois modelos de exemplo, com filosofias opostas:

- ConservativeRiskModel: pune CONCENTRAÇÃO (peso ao quadrado) — uma
  carteira 70% em BTC pesa muito mais que uma diversificada, então
  limites de classificação são mais baixos (fica "AGRESSIVA" cedo).
- AggressiveRiskModel: usa média ponderada simples, sem punir
  concentração, e usa limites de classificação mais altos — a mesma
  carteira 70% BTC pode cair em "ACEITÁVEL".

O usuário troca de modelo passando outro nome para `get_risk_model`.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from decimal import Decimal
from enum import Enum
from typing import Dict


class RiskLevel(Enum):
    CONSERVADOR = "CONSERVADOR"
    ACEITAVEL = "ACEITÁVEL"
    AGRESSIVA = "AGRESSIVA"
    EXTREMA = "EXTREMA"


class RiskModel(ABC):
    name: str = "base"

    @abstractmethod
    def score_portfolio(self, portfolio, market_snapshot, asset_registry) -> Decimal:
        ...

    @abstractmethod
    def classify(self, score: Decimal) -> RiskLevel:
        ...

    def evaluate(self, portfolio, market_snapshot, asset_registry) -> tuple[Decimal, RiskLevel]:
        score = self.score_portfolio(portfolio, market_snapshot, asset_registry)
        return score, self.classify(score)


def _weights(portfolio, market_snapshot) -> Dict[str, Decimal]:
    positions = portfolio.positions
    total_value = portfolio.total_value_usd(market_snapshot).value
    if total_value == 0:
        return {}
    weights = {}
    for asset_id, qty in positions.items():
        point = market_snapshot.get(asset_id)
        if point is None:
            continue
        weights[asset_id] = (qty * point.price_usd) / total_value
    return weights


class ConservativeRiskModel(RiskModel):
    name = "conservador"

    def score_portfolio(self, portfolio, market_snapshot, asset_registry) -> Decimal:
        weights = _weights(portfolio, market_snapshot)
        score = Decimal("0")
        for asset_id, weight in weights.items():
            asset = asset_registry[asset_id]
            risk = asset.risk_score(market_snapshot)
            # concentração pesa ao quadrado -> carteiras concentradas sobem rápido
            score += (weight ** 2) * risk * Decimal("2")
        return min(Decimal("100"), score)

    def classify(self, score: Decimal) -> RiskLevel:
        # Modelo conservador: limiares baixos -> qualquer concentração relevante
        # já empurra a carteira para AGRESSIVA/EXTREMA.
        if score < 5:
            return RiskLevel.CONSERVADOR
        if score < 15:
            return RiskLevel.ACEITAVEL
        if score < 30:
            return RiskLevel.AGRESSIVA
        return RiskLevel.EXTREMA


class AggressiveRiskModel(RiskModel):
    name = "agressivo"

    def score_portfolio(self, portfolio, market_snapshot, asset_registry) -> Decimal:
        weights = _weights(portfolio, market_snapshot)
        score = Decimal("0")
        for asset_id, weight in weights.items():
            asset = asset_registry[asset_id]
            risk = asset.risk_score(market_snapshot)
            score += weight * risk  # média ponderada simples, sem punir concentração
        return min(Decimal("100"), score)

    def classify(self, score: Decimal) -> RiskLevel:
        # Modelo agressivo: limiares altos -> tolera bem mais exposição/concentração
        # antes de soar o alarme.
        if score < 10:
            return RiskLevel.CONSERVADOR
        if score < 30:
            return RiskLevel.ACEITAVEL
        if score < 60:
            return RiskLevel.AGRESSIVA
        return RiskLevel.EXTREMA


RISK_MODEL_REGISTRY: Dict[str, type] = {
    ConservativeRiskModel.name: ConservativeRiskModel,
    AggressiveRiskModel.name: AggressiveRiskModel,
}


def get_risk_model(name: str) -> RiskModel:
    cls = RISK_MODEL_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Modelo de risco desconhecido: '{name}'. Opções: {list(RISK_MODEL_REGISTRY)}")
    return cls()
