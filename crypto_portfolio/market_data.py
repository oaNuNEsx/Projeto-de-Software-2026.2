"""
market_data.py
--------------
RF8 — Preços cientes de limite de requisições.
RF3 — Histórico reprodutível / imutável.

`PriceService`:
  - Deduplica ids e usa cache com TTL curto, então N estratégias pedindo
    o preço do BTC no mesmo instante disparam UMA chamada à CoinGecko,
    não N.
  - Usa um `TokenBucketRateLimiter` para nunca ultrapassar X chamadas
    por minuto.
  - Se mesmo assim receber HTTP 429, espera (respeitando `Retry-After`
    quando presente) e tenta de novo com backoff exponencial, em vez de
    simplesmente falhar.

`HistoricalDataStore` / `HistoricalSeries`:
  - `HistoricalSeries` guarda os pontos em uma TUPLA de `PricePoint`
    (dataclass frozen) — não há nenhum método para alterar um ponto já
    obtido.
  - `HistoricalDataStore.fetch` usa cache por `(coin_id, days)`; chamadas
    seguintes para o mesmo ativo E o mesmo período devolvem a MESMA série
    já armazenada. Períodos diferentes (ex.: 30 e 180 dias) são mantidos
    separadamente.
"""
from __future__ import annotations
import threading
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, Tuple

import requests

from .errors import RateLimitExceededError

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


@dataclass(frozen=True)
class MarketPoint:
    price_usd: Decimal
    price_brl: Decimal
    change_24h_pct: Decimal
    market_cap_rank: int


@dataclass(frozen=True)
class PricePoint:
    timestamp: int          # epoch ms
    price_usd: Decimal


class TokenBucketRateLimiter:
    """Garante no máximo `max_calls` chamadas por `period` segundos, bloqueando quando necessário."""

    def __init__(self, max_calls: int = 10, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > self.period:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_calls:
                wait_time = self.period - (now - self._timestamps[0])
                if wait_time > 0:
                    time.sleep(wait_time)
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > self.period:
                    self._timestamps.popleft()
            self._timestamps.append(time.monotonic())


def _retrying_get(session: requests.Session, limiter: TokenBucketRateLimiter,
                   url: str, params: dict, max_retries: int = 5, timeout: float = 15.0) -> dict:
    attempt = 0
    backoff = 2.0
    while True:
        limiter.acquire()
        resp = session.get(url, params=params, timeout=timeout)
        if resp.status_code == 429:
            attempt += 1
            if attempt > max_retries:
                raise RateLimitExceededError(
                    f"Limite de requisições da CoinGecko excedido repetidamente em {url}."
                )
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else backoff
            time.sleep(wait)
            backoff *= 2
            continue
        resp.raise_for_status()
        return resp.json()


class PriceService:
    """Preços 'spot' (atuais), com cache + rate limit compartilhados entre todas as estratégias."""

    def __init__(self, cache_ttl: float = 30.0, max_calls_per_minute: int = 10, session: requests.Session = None):
        self._cache: Dict[str, Tuple[float, MarketPoint]] = {}
        self._cache_ttl = cache_ttl
        self._limiter = TokenBucketRateLimiter(max_calls_per_minute, 60.0)
        self._session = session or requests.Session()
        self._lock = threading.Lock()

    def get_prices(self, coin_ids: Iterable[str]) -> Dict[str, MarketPoint]:
        """
        Ponto único de entrada para preços atuais. Deduplica `coin_ids` e só
        vai à rede para os que não estão em cache válido — isto é o que
        garante que avaliar 3 estratégias dispare 1 chamada, não 3.
        """
        coin_ids = sorted(set(coin_ids))
        now = time.monotonic()
        result: Dict[str, MarketPoint] = {}
        missing = []

        with self._lock:
            for cid in coin_ids:
                cached = self._cache.get(cid)
                if cached and (now - cached[0]) < self._cache_ttl:
                    result[cid] = cached[1]
                else:
                    missing.append(cid)

        if missing:
            fetched = self._fetch_from_api(missing)
            with self._lock:
                for cid, point in fetched.items():
                    self._cache[cid] = (time.monotonic(), point)
                    result[cid] = point
        return result

    def _fetch_from_api(self, coin_ids: list[str]) -> Dict[str, MarketPoint]:
        data = _retrying_get(
            self._session, self._limiter, f"{COINGECKO_BASE}/coins/markets",
            {"vs_currency": "usd", "ids": ",".join(coin_ids), "price_change_percentage": "24h"},
        )
        brl_prices = self._fetch_brl(coin_ids)

        points: Dict[str, MarketPoint] = {}
        for item in data:
            cid = item["id"]
            points[cid] = MarketPoint(
                price_usd=Decimal(str(item.get("current_price") or 0)),
                price_brl=brl_prices.get(cid, Decimal("0")),
                change_24h_pct=Decimal(str(item.get("price_change_percentage_24h") or 0)),
                market_cap_rank=item.get("market_cap_rank") or 9999,
            )
        return points

    def _fetch_brl(self, coin_ids: list[str]) -> Dict[str, Decimal]:
        data = _retrying_get(
            self._session, self._limiter, f"{COINGECKO_BASE}/simple/price",
            {"ids": ",".join(coin_ids), "vs_currencies": "brl"},
        )
        return {cid: Decimal(str(v.get("brl", 0))) for cid, v in data.items()}


class HistoricalSeries:
    """Sequência IMUTÁVEL de preços históricos de um único ativo (RF3)."""

    def __init__(self, coin_id: str, points: Iterable[PricePoint]):
        self._coin_id = coin_id
        self._points: Tuple[PricePoint, ...] = tuple(sorted(points, key=lambda p: p.timestamp))

    @property
    def coin_id(self) -> str:
        return self._coin_id

    @property
    def points(self) -> Tuple[PricePoint, ...]:
        return self._points

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self):
        return iter(self._points)

    def price_at_or_before(self, timestamp_ms: int) -> PricePoint | None:
        candidate = None
        for p in self._points:
            if p.timestamp <= timestamp_ms:
                candidate = p
            else:
                break
        return candidate


class HistoricalDataStore:
    """
    RF3: cada combinação `(coin_id, days)` fica congelada depois da busca.
    Chamadas repetidas com o mesmo ativo e período devolvem a mesma
    `HistoricalSeries`, enquanto períodos diferentes ficam separados.
    """

    def __init__(self, session: requests.Session = None, limiter: TokenBucketRateLimiter = None):
        self._store: Dict[Tuple[str, int], HistoricalSeries] = {}
        self._session = session or requests.Session()
        self._limiter = limiter or TokenBucketRateLimiter(10, 60.0)
        self._lock = threading.Lock()

    def fetch(self, coin_id: str, days: int = 180) -> HistoricalSeries:
        days = int(days)
        key = (coin_id, days)

        with self._lock:
            existing = self._store.get(key)
            if existing is not None:
                return existing

        raw = _retrying_get(
            self._session, self._limiter, f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": days},
        )
        points = [PricePoint(int(ts), Decimal(str(price))) for ts, price in raw.get("prices", [])]
        series = HistoricalSeries(coin_id, points)

        with self._lock:
            self._store.setdefault(key, series)
            return self._store[key]

    def get(self, coin_id: str, days: int = 180) -> HistoricalSeries | None:
        return self._store.get((coin_id, int(days)))
