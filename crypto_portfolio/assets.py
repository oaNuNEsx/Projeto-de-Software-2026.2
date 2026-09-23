"""
assets.py
---------
RF4 — Tipos de ativos, cada um com perfil de risco adequado ao seu tipo.

Três tipos são modelados, cada um com uma métrica de risco DIFERENTE:

- COIN (ex.: BTC, ETH): risco = volatilidade de 24h.
- STABLECOIN (ex.: USDT, USDC): risco = desvio da paridade de 1 USD.
  Uma stablecoin cotada a $0,97 é mais arriscada que uma a $1,00, mesmo
  que sua "volatilidade" numérica seja minúscula — por isso ela NÃO usa
  a mesma fórmula da COIN.
- TOKEN (altcoins menores): risco = volatilidade + penalidade por baixa
  capitalização/liquidez (market cap rank).

Cada `Asset` sabe calcular seu próprio `risk_score`, então adicionar um
novo tipo de ativo não exige mexer em nada fora deste arquivo.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class AssetType(Enum):
    COIN = "coin"
    STABLECOIN = "stablecoin"
    TOKEN = "token"


@dataclass(frozen=True)
class Asset:
    id: str            # id da CoinGecko, ex: "bitcoin"
    symbol: str         # ex: "BTC"
    name: str
    asset_type: AssetType

    def risk_score(self, market_snapshot: dict) -> Decimal:
        """
        Retorna um score de 0 (sem risco) a 100 (risco extremo),
        calculado de forma DIFERENTE conforme o tipo do ativo.
        """
        point = market_snapshot.get(self.id)
        if point is None:
            raise ValueError(f"Sem dados de mercado para calcular risco de '{self.id}'.")

        if self.asset_type == AssetType.STABLECOIN:
            deviation = abs(Decimal("1") - point.price_usd)
            # deviation de 0.03 (3 centavos) já é bem significativo p/ uma stable
            return min(Decimal("100"), deviation * Decimal("1000"))

        if self.asset_type == AssetType.COIN:
            change = abs(point.change_24h_pct)
            return min(Decimal("100"), change * Decimal("4"))

        if self.asset_type == AssetType.TOKEN:
            change = abs(point.change_24h_pct)
            rank = point.market_cap_rank or 9999
            if rank > 100:
                rank_penalty = Decimal("30")
            elif rank > 30:
                rank_penalty = Decimal("15")
            else:
                rank_penalty = Decimal("0")
            return min(Decimal("100"), change * Decimal("3") + rank_penalty)

        raise ValueError(f"Tipo de ativo desconhecido: {self.asset_type}")


# Registro padrão de ativos suportados pela demo (facilmente extensível).
DEFAULT_ASSET_REGISTRY = {
    "bitcoin": Asset("bitcoin", "BTC", "Bitcoin", AssetType.COIN),
    "ethereum": Asset("ethereum", "ETH", "Ethereum", AssetType.COIN),
    "tether": Asset("tether", "USDT", "Tether", AssetType.STABLECOIN),
    "usd-coin": Asset("usd-coin", "USDC", "USD Coin", AssetType.STABLECOIN),
    "solana": Asset("solana", "SOL", "Solana", AssetType.TOKEN),
    "dogecoin": Asset("dogecoin", "DOGE", "Dogecoin", AssetType.TOKEN),
}
