"""
Testes do padrão estrutural Decorator aplicado às estratégias (sem rede).

Cobrem:
- delegação transparente (StrategyDecorator repassa evaluate ao wrapped)
- LoggingDecorator registra cada recomendação internamente
- RiskLimitDecorator filtra compras de ativos acima do limiar de risco
- composição (empilhamento) de decorators
- compatibilidade com o Tournament (decorator É uma Strategy)
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from crypto_portfolio.assets import DEFAULT_ASSET_REGISTRY
from crypto_portfolio.audit import TradeSide
from crypto_portfolio.market_data import MarketPoint, HistoricalSeries, PricePoint
from crypto_portfolio.portfolio import Portfolio
from crypto_portfolio.strategies import (
    Strategy, Action, Recommendation,
    HodlStrategy, DcaStrategy, StopLossStrategy,
    StrategyDecorator, LoggingDecorator, RiskLimitDecorator,
    available_strategies,
)
from crypto_portfolio.tournament import Tournament

DAY_MS = 86_400_000


def snapshot_com_risco_alto():
    """BTC com queda de 24h de 20% → risk_score alto; ETH estável."""
    return {
        "bitcoin": MarketPoint(Decimal("60000"), Decimal("300000"), Decimal("20"), 1),
        "ethereum": MarketPoint(Decimal("3000"), Decimal("15000"), Decimal("1"), 2),
        "tether": MarketPoint(Decimal("1.00"), Decimal("5.00"), Decimal("0.1"), 5),
    }


def carteira_simples():
    return Portfolio("USD", Decimal("10000"), DEFAULT_ASSET_REGISTRY)


# ---------------------------------------------------------------- StrategyDecorator (base)

def test_decorator_delega_evaluate_ao_wrapped():
    hodl = HodlStrategy()
    decorado = LoggingDecorator(hodl)

    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()

    recs_original = hodl.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})
    recs_decorado = decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    # O decorator devolve as mesmas recomendações (HODL → HOLD)
    assert len(recs_decorado) == len(recs_original)
    assert recs_decorado[0].action == recs_original[0].action


def test_decorator_delega_nome_ao_wrapped():
    hodl = HodlStrategy()
    decorado = LoggingDecorator(hodl)
    assert decorado.name == hodl.name == "HODL"


def test_decorator_e_instancia_de_strategy():
    """O decorator É uma Strategy — esse é o ponto do padrão."""
    decorado = LoggingDecorator(HodlStrategy())
    assert isinstance(decorado, Strategy)


# ---------------------------------------------------------------- LoggingDecorator

def test_logging_registra_cada_recomendacao():
    dca = DcaStrategy()
    decorado = LoggingDecorator(dca)

    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()
    decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    log = decorado.log
    assert len(log) >= 1
    assert "DCA" in log[0]
    assert "COMPRAR" in log[0] or "MANTER" in log[0]


def test_logging_acumula_entre_chamadas():
    dca = DcaStrategy()
    decorado = LoggingDecorator(dca)

    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()
    decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})
    decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    assert len(decorado.log) >= 2


def test_logging_limpar_log():
    dca = DcaStrategy()
    decorado = LoggingDecorator(dca)

    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()
    decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})
    assert len(decorado.log) >= 1

    decorado.limpar_log()
    assert len(decorado.log) == 0


def test_logging_devolve_copia_defensiva():
    decorado = LoggingDecorator(HodlStrategy())
    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()
    decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    log = decorado.log
    assert isinstance(log, tuple)  # tupla, imutável


# ---------------------------------------------------------------- RiskLimitDecorator

def test_risk_limit_filtra_compra_de_ativo_arriscado():
    """DCA tenta comprar BTC (risco alto por queda de 20%). O decorator bloqueia."""
    dca = DcaStrategy(target_asset="bitcoin", amount_per_cycle=Decimal("50"))
    decorado = RiskLimitDecorator(dca, max_risk=Decimal("30"))

    snapshot = snapshot_com_risco_alto()
    # BTC risk_score = abs(20) * 4 = 80, que excede max_risk=30
    carteira = carteira_simples()
    recs = decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    # A recomendação de compra foi convertida em HOLD
    assert all(r.action == Action.HOLD for r in recs)
    assert any("risco" in r.reason.lower() for r in recs)


def test_risk_limit_permite_compra_de_ativo_seguro():
    """DCA tenta comprar ETH (risco baixo). O decorator permite."""
    dca = DcaStrategy(target_asset="ethereum", amount_per_cycle=Decimal("50"))
    decorado = RiskLimitDecorator(dca, max_risk=Decimal("30"))

    snapshot = snapshot_com_risco_alto()
    # ETH risk_score = abs(1) * 4 = 4, abaixo de max_risk=30
    carteira = carteira_simples()
    recs = decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    assert any(r.action == Action.BUY for r in recs)


def test_risk_limit_nao_filtra_sell_nem_hold():
    """Stop-Loss recomenda SELL. O decorator NÃO filtra vendas nem holds."""
    stop = StopLossStrategy(drop_threshold_pct=Decimal("10"))
    decorado = RiskLimitDecorator(stop, max_risk=Decimal("1"))  # limiar mínimo

    snapshot = snapshot_com_risco_alto()
    # BTC caiu 20% → Stop-Loss quer vender tudo
    carteira = carteira_simples()
    carteira.execute_trade("bitcoin", TradeSide.BUY, Decimal("0.1"), Decimal("60000"))
    recs = decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    # SELL e HOLD passam direto, não são filtrados
    acoes = [r.action for r in recs]
    assert Action.SELL in acoes or Action.HOLD in acoes


# ---------------------------------------------------------------- empilhamento de decorators

def test_decorators_empilham():
    """Logging + RiskLimit juntos: logging registra, risk limit filtra."""
    dca = DcaStrategy(target_asset="bitcoin", amount_per_cycle=Decimal("50"))
    decorado = LoggingDecorator(RiskLimitDecorator(dca, max_risk=Decimal("30")))

    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()
    recs = decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    # RiskLimit filtrou a compra → HOLD
    assert all(r.action == Action.HOLD for r in recs)
    # Logging registrou o resultado filtrado
    assert len(decorado.log) >= 1


def test_ordem_dos_decorators_importa():
    """RiskLimit(Logging(DCA)): logging vê a recomendação original, risk limit filtra depois."""
    dca = DcaStrategy(target_asset="bitcoin", amount_per_cycle=Decimal("50"))
    logging_inner = LoggingDecorator(dca)
    decorado = RiskLimitDecorator(logging_inner, max_risk=Decimal("30"))

    snapshot = snapshot_com_risco_alto()
    carteira = carteira_simples()
    recs = decorado.evaluate(carteira, snapshot, DEFAULT_ASSET_REGISTRY, {})

    # O resultado final é filtrado (HOLD)
    assert all(r.action == Action.HOLD for r in recs)
    # Mas o LoggingDecorator interno viu a recomendação ORIGINAL (BUY)
    assert len(logging_inner.log) >= 1
    assert "COMPRAR" in logging_inner.log[0]


# ---------------------------------------------------------------- decorators não estão no registro

def test_decorators_nao_aparecem_no_registro_de_estrategias():
    """Decorators não são estratégias registradas — são wrappers."""
    nomes = available_strategies()
    assert "StrategyDecorator" not in nomes
    assert "LoggingDecorator" not in nomes
    assert "RiskLimitDecorator" not in nomes
