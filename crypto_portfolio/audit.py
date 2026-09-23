"""
audit.py
--------
RF7 — Trilha de auditoria imutável.

`Trade` é um dataclass `frozen=True`: uma vez criado, nenhum de seus
campos pode ser reatribuído (tentar fazê-lo levanta `FrozenInstanceError`).

`AuditTrail` só oferece:
  - `record(...)`  -> cria e adiciona um novo Trade (única forma de escrita)
  - `entries`       -> devolve uma TUPLA (cópia, imutável) dos trades

Não existe `remove`, `edit`, `update`, `clear` ou qualquer outro método
de mutação — nem a própria `Portfolio` tem acesso a operações desse tipo,
porque elas simplesmente não existem na classe.
"""
from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple


class TradeSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Trade:
    trade_id: str
    asset_id: str
    side: TradeSide
    quantity: Decimal
    price_usd: Decimal
    cash_currency: str
    cash_amount: Decimal
    timestamp: float


class AuditTrail:
    def __init__(self):
        self._entries: list[Trade] = []
        self._lock = threading.Lock()
        self._counter = 0

    def record(self, asset_id: str, side: TradeSide, quantity: Decimal, price_usd: Decimal,
               cash_currency: str, cash_amount: Decimal) -> Trade:
        with self._lock:
            self._counter += 1
            trade = Trade(
                trade_id=f"T{self._counter:06d}",
                asset_id=asset_id,
                side=side,
                quantity=quantity,
                price_usd=price_usd,
                cash_currency=cash_currency,
                cash_amount=cash_amount,
                timestamp=time.time(),
            )
            self._entries.append(trade)
            return trade

    @property
    def entries(self) -> Tuple[Trade, ...]:
        """Sempre uma cópia — mutar a tupla retornada não afeta o histórico real."""
        with self._lock:
            return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self.entries)
