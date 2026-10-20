"""
portfolio_builder.py
--------------------
Builder para montar uma `Portfolio` em etapas nomeadas, validando tudo ANTES de a
carteira existir.

Toda posição é aplicada por `Portfolio.execute_trade()`. Por isso RF1 (carteira
protegida), RF6 (erros específicos) e RF7 (trilha de auditoria) continuam valendo
para a carteira montada: o Builder nunca escreve estado diretamente.

Uso:
    carteira = (PortfolioBuilder(DEFAULT_ASSET_REGISTRY)
                .com_moeda_base("USD")
                .com_caixa_inicial(10000)
                .com_precos(snapshot)
                .com_posicao_por_peso("bitcoin", "0.35")   # 35% do caixa inicial em BTC
                .com_posicao("ethereum", 2, 3000)          # 2 ETH a USD 3000
                .build())
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from .assets import Asset
from .audit import AuditTrail, TradeSide
from .market_data import MarketPoint
from .portfolio import Portfolio


class PortfolioBuilder:
    def __init__(self, asset_registry: Dict[str, Asset]):
        self._registry = asset_registry
        self._moeda = "USD"
        self._caixa = Decimal("0")
        self._precos: Dict[str, MarketPoint] | None = None
        self._pesos: Dict[str, Decimal] = {}
        # (asset_id, quantidade, preço em USD, câmbio USD -> moeda base)
        self._ordens: List[Tuple[str, Decimal, Decimal, Decimal]] = []

    # ---------------- etapas (cada uma devolve o próprio builder) ----------------
    def com_moeda_base(self, moeda: str) -> "PortfolioBuilder":
        self._moeda = moeda
        return self

    def com_caixa_inicial(self, valor) -> "PortfolioBuilder":
        self._caixa = Decimal(str(valor))
        return self

    def com_precos(self, snapshot: Dict[str, MarketPoint]) -> "PortfolioBuilder":
        """Preços usados para converter pesos em quantidades (ver com_posicao_por_peso)."""
        self._precos = snapshot
        return self

    def com_posicao_por_peso(self, asset_id: str, peso) -> "PortfolioBuilder":
        """Compra `peso` (0 a 1) do caixa inicial no ativo, ao preço informado em com_precos()."""
        self._pesos[asset_id] = Decimal(str(peso))
        return self

    def com_posicao(self, asset_id: str, quantidade, preco_usd,
                    fx_usd_to_base=Decimal("1")) -> "PortfolioBuilder":
        """Compra uma quantidade fixa do ativo (mesmos argumentos de Portfolio.execute_trade)."""
        self._ordens.append((asset_id, Decimal(str(quantidade)), Decimal(str(preco_usd)),
                             Decimal(str(fx_usd_to_base))))
        return self

    # ---------------- validação (única definição da regra dos pesos) ----------------
    @staticmethod
    def validar_pesos(pesos: Dict[str, Decimal]) -> None:
        """Regra que o Tournament aplicava sozinho: soma entre 0 e 1 e nenhum peso negativo."""
        total = sum(pesos.values(), Decimal("0"))
        if total < 0 or total > 1:
            raise ValueError("A soma dos pesos iniciais deve ficar entre 0 e 1.")
        if any(peso < 0 for peso in pesos.values()):
            raise ValueError("Pesos iniciais não podem ser negativos.")

    # ---------------- montagem ----------------
    def build(self) -> Portfolio:
        # Tudo é validado antes de existir uma carteira.
        self.validar_pesos(self._pesos)
        if self._pesos and self._precos is None:
            raise ValueError("Posições por peso exigem preços: chame com_precos(snapshot).")

        carteira = Portfolio(self._moeda, self._caixa, self._registry, AuditTrail())

        for asset_id, peso in self._pesos.items():
            ponto = self._precos.get(asset_id)
            if peso == 0 or ponto is None or ponto.price_usd <= 0:
                continue
            quantidade = ((self._caixa * peso) / ponto.price_usd).quantize(Decimal("0.00000001"))
            if quantidade > 0:
                carteira.execute_trade(asset_id, TradeSide.BUY, quantidade, ponto.price_usd,
                                       fx_usd_to_base=Decimal("1"))

        # Se alguma compra falhar (RF6), a exceção sobe e nenhuma carteira é devolvida.
        for asset_id, quantidade, preco_usd, fx in self._ordens:
            carteira.execute_trade(asset_id, TradeSide.BUY, quantidade, preco_usd, fx_usd_to_base=fx)

        return carteira