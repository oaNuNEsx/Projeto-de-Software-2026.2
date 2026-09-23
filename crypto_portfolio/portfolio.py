"""
portfolio.py
------------
RF1 — Carteira protegida.

`Portfolio` guarda `__cash` e `__positions` com name-mangling (atributos
"privados" de verdade em Python: `self.__cash` vira `_Portfolio__cash`).
Não existe NENHUM setter público para eles — as únicas formas de ler são
propriedades que devolvem cópias/valores imutáveis (`Amount` é frozen;
`positions` devolve um `dict` novo a cada chamada).

A ÚNICA forma de alterar saldo ou posições é `execute_trade`, que:
  1. Valida tudo (ativo existe, quantidade/preço/taxa > 0, saldo/posição suficiente)
     ANTES de tocar em qualquer estado interno — se alguma validação
     falhar, uma exceção específica (RF6) é lançada e o estado
     permanece 100% intocado.
  2. Só então aplica a mutação e grava na `AuditTrail` (RF7).

Isso torna "vender 0,5 BTC tendo 0,3" impossível de corromper o estado:
a exceção `InsufficientPositionError` é lançada antes de qualquer débito.
"""
from __future__ import annotations
import threading
from decimal import Decimal
from typing import Dict

from .money import Amount
from .errors import (
    AssetNotFoundError,
    InsufficientBalanceError,
    InsufficientPositionError,
    InvalidQuantityError,
    InvalidPriceError,
    InvalidExchangeRateError,
)
from .audit import AuditTrail, Trade, TradeSide
from .assets import Asset


class Portfolio:
    def __init__(self, base_currency: str, initial_cash: Decimal,
                 asset_registry: Dict[str, Asset], audit_trail: AuditTrail | None = None):
        self.__base_currency = base_currency.upper()
        self.__cash = Amount(Decimal(str(initial_cash)), self.__base_currency)
        self.__positions: Dict[str, Decimal] = {}
        self.__asset_registry = asset_registry
        self.__audit = audit_trail if audit_trail is not None else AuditTrail()
        self.__lock = threading.Lock()

    # ---------------- leitura somente ----------------
    @property
    def base_currency(self) -> str:
        return self.__base_currency

    @property
    def cash(self) -> Amount:
        return self.__cash  # Amount é imutável (frozen)

    @property
    def positions(self) -> Dict[str, Decimal]:
        return dict(self.__positions)  # cópia defensiva

    @property
    def audit_trail(self) -> AuditTrail:
        return self.__audit

    def quantity_of(self, asset_id: str) -> Decimal:
        return self.__positions.get(asset_id, Decimal("0"))

    def total_value_usd(self, market_snapshot: dict) -> Amount:
        total = Decimal("0")
        for asset_id, qty in self.__positions.items():
            point = market_snapshot.get(asset_id)
            if point is not None:
                total += qty * point.price_usd
        return Amount(total, "USD")

    # ---------------- única porta de escrita ----------------
    def execute_trade(self, asset_id: str, side: TradeSide, quantity, price_usd,
                       fx_usd_to_base: Decimal = Decimal("1")) -> Trade:
        """
        Único método capaz de alterar `cash`/`positions`.
        Levanta uma exceção específica (RF6) e NÃO altera nada se a
        negociação for inválida por qualquer motivo.
        """
        if asset_id not in self.__asset_registry:
            raise AssetNotFoundError(asset_id)

        quantity = Decimal(str(quantity))
        if quantity <= 0:
            raise InvalidQuantityError(quantity)

        price_usd = Decimal(str(price_usd))
        if price_usd <= 0:
            raise InvalidPriceError(price_usd)

        fx_usd_to_base = Decimal(str(fx_usd_to_base))
        if fx_usd_to_base <= 0:
            raise InvalidExchangeRateError(fx_usd_to_base)

        cost_usd = quantity * price_usd
        cost_base_value = cost_usd * fx_usd_to_base
        cost_amount = Amount(cost_base_value, self.__base_currency)

        with self.__lock:
            if side == TradeSide.BUY:
                if cost_amount > self.__cash:
                    raise InsufficientBalanceError(
                        self.__base_currency, cost_amount.value, self.__cash.value
                    )
                new_cash = self.__cash - cost_amount
                new_qty = self.__positions.get(asset_id, Decimal("0")) + quantity
                # só agora, com tudo validado, mutamos o estado:
                self.__cash = new_cash
                self.__positions[asset_id] = new_qty

            elif side == TradeSide.SELL:
                held = self.__positions.get(asset_id, Decimal("0"))
                if quantity > held:
                    raise InsufficientPositionError(asset_id, quantity, held)
                new_qty = held - quantity
                new_cash = self.__cash + cost_amount
                self.__cash = new_cash
                if new_qty == 0:
                    self.__positions.pop(asset_id, None)
                else:
                    self.__positions[asset_id] = new_qty
            else:
                raise ValueError(f"Lado de negociação desconhecido: {side}")

            trade = self.__audit.record(
                asset_id=asset_id,
                side=side,
                quantity=quantity,
                price_usd=price_usd,
                cash_currency=self.__base_currency,
                cash_amount=cost_base_value,
            )
        return trade
