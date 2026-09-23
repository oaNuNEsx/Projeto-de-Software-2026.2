"""
assets.py
---------
RF4 — Abstração, herança e polimorfismo para os tipos de criptoativos.

`Asset` define o contrato comum. `Coin`, `Stablecoin` e `Token` herdam
desse contrato e implementam seu próprio cálculo de risco.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import ClassVar


class AssetType(Enum):
    COIN = "coin"
    STABLECOIN = "stablecoin"
    TOKEN = "token"


@dataclass(frozen=True)
class Asset(ABC):
    """Abstração comum para qualquer criptoativo suportado."""

    id: str
    symbol: str
    name: str
    asset_type: ClassVar[AssetType]

    def _market_point(self, market_snapshot: dict):
        point = market_snapshot.get(self.id)
        if point is None:
            raise ValueError(f"Sem dados de mercado para calcular risco de '{self.id}'.")
        return point

    @abstractmethod
    def risk_score(self, market_snapshot: dict) -> Decimal:
        """Calcula um score de 0 a 100 conforme a natureza do ativo."""


@dataclass(frozen=True)
class Coin(Asset):
    """Moeda consolidada: risco baseado na volatilidade de 24 horas."""

    asset_type: ClassVar[AssetType] = AssetType.COIN

    def risk_score(self, market_snapshot: dict) -> Decimal:
        point = self._market_point(market_snapshot)
        return min(Decimal("100"), abs(point.change_24h_pct) * Decimal("4"))


@dataclass(frozen=True)
class Stablecoin(Asset):
    """Stablecoin: risco baseado no afastamento da paridade de 1 USD."""

    asset_type: ClassVar[AssetType] = AssetType.STABLECOIN

    def risk_score(self, market_snapshot: dict) -> Decimal:
        point = self._market_point(market_snapshot)
        deviation = abs(Decimal("1") - point.price_usd)
        return min(Decimal("100"), deviation * Decimal("1000"))


@dataclass(frozen=True)
class Token(Asset):
    """Token menor: combina volatilidade e penalidade por baixa liquidez."""

    asset_type: ClassVar[AssetType] = AssetType.TOKEN

    def risk_score(self, market_snapshot: dict) -> Decimal:
        point = self._market_point(market_snapshot)
        rank = point.market_cap_rank or 9999
        if rank > 100:
            rank_penalty = Decimal("30")
        elif rank > 30:
            rank_penalty = Decimal("15")
        else:
            rank_penalty = Decimal("0")
        return min(
            Decimal("100"),
            abs(point.change_24h_pct) * Decimal("3") + rank_penalty,
        )


DEFAULT_ASSET_REGISTRY = {
    "bitcoin": Coin("bitcoin", "BTC", "Bitcoin"),
    "ethereum": Coin("ethereum", "ETH", "Ethereum"),
    "tether": Stablecoin("tether", "USDT", "Tether"),
    "usd-coin": Stablecoin("usd-coin", "USDC", "USD Coin"),
    "solana": Token("solana", "SOL", "Solana"),
    "dogecoin": Token("dogecoin", "DOGE", "Dogecoin"),
}
