"""
money.py
--------
RF2 — Sem mistura implícita de moedas.

`Amount` é o ÚNICO jeito de representar valor monetário no sistema.
Ele carrega a moeda junto com o número e recusa (`CurrencyMismatchError`)
qualquer operação aritmética ou de comparação entre moedas diferentes.

Não existe nenhuma função solta de "somar valores" que aceite dois
números crus — todo valor no sistema é um `Amount`, então o erro de
somar BRL com USD deixa de ser um bug possível e vira um TypeError/
CurrencyMismatchError em tempo de execução (idealmente detectável até
por um type checker, já que os métodos exigem `Amount`).
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


class CurrencyMismatchError(Exception):
    """Lançado sempre que se tenta operar dois `Amount` de moedas diferentes."""
    def __init__(self, currency_a: str, currency_b: str):
        super().__init__(
            f"Operação inválida: não é possível combinar valores em "
            f"'{currency_a}' e '{currency_b}' sem uma conversão explícita "
            f"(use Amount.convert_to)."
        )
        self.currency_a = currency_a
        self.currency_b = currency_b


@dataclass(frozen=True)
class Amount:
    value: Decimal
    currency: str

    def __post_init__(self):
        v = self.value if isinstance(self.value, Decimal) else Decimal(str(self.value))
        object.__setattr__(self, "value", v)
        object.__setattr__(self, "currency", self.currency.upper())

    # ---- guarda de compatibilidade de moeda ----
    def _same_currency_or_raise(self, other: "Amount") -> None:
        if not isinstance(other, Amount):
            raise TypeError(
                f"Só é possível operar Amount com Amount, não com {type(other).__name__}."
            )
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency)

    # ---- aritmética segura ----
    def __add__(self, other: "Amount") -> "Amount":
        self._same_currency_or_raise(other)
        return Amount(self.value + other.value, self.currency)

    def __sub__(self, other: "Amount") -> "Amount":
        self._same_currency_or_raise(other)
        return Amount(self.value - other.value, self.currency)

    def __mul__(self, scalar) -> "Amount":
        if isinstance(scalar, Amount):
            raise TypeError(
                "Não é possível multiplicar Amount por Amount (o resultado teria "
                "moeda ambígua); multiplique por um número puro."
            )
        return Amount(self.value * Decimal(str(scalar)), self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> "Amount":
        return Amount(-self.value, self.currency)

    # ---- comparação segura ----
    def __eq__(self, other) -> bool:
        if not isinstance(other, Amount):
            return NotImplemented
        return self.currency == other.currency and self.value == other.value

    def __lt__(self, other: "Amount") -> bool:
        self._same_currency_or_raise(other)
        return self.value < other.value

    def __le__(self, other: "Amount") -> bool:
        self._same_currency_or_raise(other)
        return self.value <= other.value

    def __gt__(self, other: "Amount") -> bool:
        self._same_currency_or_raise(other)
        return self.value > other.value

    def __ge__(self, other: "Amount") -> bool:
        self._same_currency_or_raise(other)
        return self.value >= other.value

    def __hash__(self):
        return hash((self.value, self.currency))

    # ---- a ÚNICA porta de saída de uma moeda para outra ----
    def convert_to(self, target_currency: str, rate: Decimal) -> "Amount":
        """
        Conversão EXPLÍCITA: `rate` é quanto vale 1 unidade de `self.currency`
        em `target_currency`. É o único caminho legítimo para "misturar" moedas —
        e ele sempre produz um novo `Amount`, nunca um número cru.
        """
        rate = Decimal(str(rate))
        converted = (self.value * rate).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        return Amount(converted, target_currency)

    def __repr__(self) -> str:
        return f"{self.value} {self.currency}"
