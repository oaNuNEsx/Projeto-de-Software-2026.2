"""
errors.py
---------
RF6 — Erros de negociação distinguíveis.

Cada condição de falha tem sua PRÓPRIA classe de exceção, todas
derivando de `TradingError`. Isso permite que qualquer camada acima
(CLI, API, testes) faça `except InsufficientBalanceError` separado de
`except AssetNotFoundError` — nunca um "except genérico" escondendo
qual foi o problema real.
"""


class TradingError(Exception):
    """Classe base de todos os erros de negociação do sistema."""


class AssetNotFoundError(TradingError):
    """O identificador de ativo informado não existe no registro de ativos."""
    def __init__(self, asset_id: str):
        super().__init__(f"Ativo '{asset_id}' não encontrado no registro de ativos.")
        self.asset_id = asset_id


class InvalidQuantityError(TradingError):
    """Quantidade de negociação inválida (zero, negativa ou não numérica)."""
    def __init__(self, quantity):
        super().__init__(f"Quantidade inválida para negociação: {quantity!r}. Deve ser > 0.")
        self.quantity = quantity




class InvalidPriceError(TradingError):
    """Preço de negociação inválido (zero ou negativo)."""
    def __init__(self, price):
        super().__init__(f"Preço inválido para negociação: {price!r}. Deve ser > 0.")
        self.price = price


class InvalidExchangeRateError(TradingError):
    """Taxa de câmbio inválida (zero ou negativa)."""
    def __init__(self, rate):
        super().__init__(f"Taxa de câmbio inválida: {rate!r}. Deve ser > 0.")
        self.rate = rate


class InsufficientBalanceError(TradingError):
    """Não há caixa suficiente na moeda-base da carteira para completar a compra."""
    def __init__(self, currency: str, needed, available):
        super().__init__(
            f"Saldo insuficiente em {currency}: necessário {needed}, disponível {available}."
        )
        self.currency = currency
        self.needed = needed
        self.available = available


class InsufficientPositionError(TradingError):
    """Não há unidades suficientes do ativo na carteira para completar a venda."""
    def __init__(self, asset_id: str, needed, available):
        super().__init__(
            f"Posição insuficiente em {asset_id}: tentando vender {needed}, "
            f"mas a carteira possui apenas {available}."
        )
        self.asset_id = asset_id
        self.needed = needed
        self.available = available


class RateLimitExceededError(TradingError):
    """O provedor de preços (CoinGecko) recusou repetidamente por limite de requisições."""


class ImmutableDataError(TradingError):
    """Tentativa de alterar um dado que o sistema garante ser imutável (histórico, auditoria)."""
    def __init__(self, message: str = "Este dado é imutável e não pode ser alterado ou removido."):
        super().__init__(message)
