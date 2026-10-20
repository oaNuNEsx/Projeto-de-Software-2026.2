"""
Testes do padrão Prototype: `Portfolio.clonar()`, `AuditTrail.clonar()` e o uso
no `Tournament.run()` (sem rede).

Os dois últimos grupos documentam POR QUE o clone é escrito à mão: copiar com
`copy` não funciona para estes objetos.
"""
import copy
import sys
import threading
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from crypto_portfolio.assets import Coin, DEFAULT_ASSET_REGISTRY
from crypto_portfolio.audit import AuditTrail, TradeSide
from crypto_portfolio.errors import InsufficientPositionError
from crypto_portfolio.market_data import HistoricalSeries, PricePoint
from crypto_portfolio.portfolio import Portfolio
from crypto_portfolio.tournament import Tournament

DAY_MS = 86_400_000
CAPITAL = Decimal("10000")


def carteira_base():
    """10.000 USD de caixa, depois 10 BTC comprados a 100 -> caixa 9.000 e 1 negociação na auditoria."""
    carteira = Portfolio("USD", CAPITAL, DEFAULT_ASSET_REGISTRY)
    carteira.execute_trade("bitcoin", TradeSide.BUY, Decimal("10"), Decimal("100"))
    return carteira


def historicos_de_teste():
    """Mesmo histórico sintético das demonstrações: 30 dias, com uma queda forte do BTC."""
    btc, eth = [], []
    for i in range(30):
        if i < 10:
            preco_btc = Decimal(100 + i * 2)
        elif i == 10:
            preco_btc = Decimal("80")
        else:
            preco_btc = Decimal(80 + (i - 10) * 3)
        btc.append(PricePoint(i * DAY_MS, preco_btc))
        eth.append(PricePoint(i * DAY_MS, Decimal(50 + i)))
    return {
        "bitcoin": HistoricalSeries("bitcoin", btc),
        "ethereum": HistoricalSeries("ethereum", eth),
    }


# ------------------------------------------------------------------ Portfolio.clonar()

def test_clone_comeca_com_o_mesmo_estado():
    base = carteira_base()
    clone = base.clonar()

    assert clone is not base
    assert clone.base_currency == base.base_currency
    assert clone.cash == base.cash
    assert clone.positions == base.positions
    assert clone.audit_trail.entries == base.audit_trail.entries


def test_operar_no_clone_nao_altera_a_original():
    base = carteira_base()
    clone = base.clonar()

    clone.execute_trade("bitcoin", TradeSide.BUY, Decimal("5"), Decimal("100"))

    assert clone.positions == {"bitcoin": Decimal("15")}
    assert clone.cash.value == Decimal("8500")
    assert len(clone.audit_trail) == 2
    assert base.positions == {"bitcoin": Decimal("10")}
    assert base.cash.value == Decimal("9000")
    assert len(base.audit_trail) == 1


def test_operar_na_original_nao_altera_o_clone():
    base = carteira_base()
    clone = base.clonar()

    base.execute_trade("bitcoin", TradeSide.SELL, Decimal("10"), Decimal("100"))

    assert base.positions == {}
    assert clone.positions == {"bitcoin": Decimal("10")}
    assert clone.cash.value == Decimal("9000")
    assert len(clone.audit_trail) == 1


def test_clones_sao_independentes_entre_si():
    base = carteira_base()
    a, b = base.clonar(), base.clonar()

    a.execute_trade("bitcoin", TradeSide.BUY, Decimal("5"), Decimal("100"))
    b.execute_trade("bitcoin", TradeSide.SELL, Decimal("10"), Decimal("100"))

    assert a.positions == {"bitcoin": Decimal("15")}
    assert b.positions == {}
    assert base.positions == {"bitcoin": Decimal("10")}
    assert a.audit_trail is not b.audit_trail


def test_clone_compartilha_o_registro_de_ativos_de_proposito():
    registro = dict(DEFAULT_ASSET_REGISTRY)
    base = Portfolio("USD", Decimal("1000"), registro)
    clone = base.clonar()

    # O registro é dado de referência, não estado da carteira: um ativo novo vale para as duas.
    registro["novo-ativo"] = Coin("novo-ativo", "NVO", "Novo Ativo")
    base.execute_trade("novo-ativo", TradeSide.BUY, Decimal("1"), Decimal("10"))
    clone.execute_trade("novo-ativo", TradeSide.BUY, Decimal("1"), Decimal("10"))

    assert base.quantity_of("novo-ativo") == clone.quantity_of("novo-ativo") == Decimal("1")


def test_clone_nao_abre_porta_de_escrita_e_mantem_as_validacoes():
    clone = carteira_base().clonar()

    with pytest.raises(InsufficientPositionError):
        clone.execute_trade("bitcoin", TradeSide.SELL, Decimal("11"), Decimal("100"))

    assert clone.positions == {"bitcoin": Decimal("10")}
    assert clone.cash.value == Decimal("9000")


def test_clonar_durante_operacoes_concorrentes_nunca_captura_estado_pela_metade():
    base = Portfolio("USD", Decimal("1000000"), DEFAULT_ASSET_REGISTRY)
    terminou = threading.Event()

    def operar():
        for _ in range(4000):
            base.execute_trade("bitcoin", TradeSide.BUY, Decimal("1"), Decimal("10"))
        terminou.set()

    intervalo_original = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # força trocas de thread frequentes, para expor um estado torn
    try:
        trabalhador = threading.Thread(target=operar)
        trabalhador.start()
        clones = []
        while not terminou.is_set() and len(clones) < 1500:
            clones.append(base.clonar())
        trabalhador.join()
    finally:
        sys.setswitchinterval(intervalo_original)
    clones.append(base.clonar())

    # Invariante de toda carteira consistente: cada compra tira 10 do caixa, soma 1 BTC e 1 linha na auditoria.
    for clone in clones:
        quantidade = clone.quantity_of("bitcoin")
        assert clone.cash.value == Decimal("1000000") - Decimal("10") * quantidade
        assert Decimal(len(clone.audit_trail)) == quantidade


# ------------------------------------------------------------------ AuditTrail.clonar()

def test_clone_da_auditoria_herda_historico_e_continua_a_numeracao():
    base = carteira_base()
    clone = base.clonar()

    trade_do_clone = clone.execute_trade("bitcoin", TradeSide.BUY, Decimal("1"), Decimal("100"))
    trade_da_original = base.execute_trade("bitcoin", TradeSide.BUY, Decimal("2"), Decimal("100"))

    assert trade_do_clone.trade_id == trade_da_original.trade_id == "T000002"
    assert trade_do_clone.quantity == Decimal("1") and trade_da_original.quantity == Decimal("2")
    assert [t.trade_id for t in clone.audit_trail.entries] == ["T000001", "T000002"]
    assert [t.trade_id for t in base.audit_trail.entries] == ["T000001", "T000002"]


def test_auditoria_clonada_nao_compartilha_a_lista_de_negociacoes():
    original = AuditTrail()
    original.record("bitcoin", TradeSide.BUY, Decimal("1"), Decimal("100"), "USD", Decimal("100"))
    clone = original.clonar()

    clone.record("bitcoin", TradeSide.BUY, Decimal("1"), Decimal("100"), "USD", Decimal("100"))

    assert len(original) == 1
    assert len(clone) == 2


# ------------------------------------------------------------------ por que copy não serve

def test_motivo_1_deepcopy_ingenuo_falha_por_causa_do_lock():
    """Se um dia o Lock sair de Portfolio/AuditTrail, este teste deve ser revisto (e a justificativa também)."""
    with pytest.raises(TypeError, match="lock"):
        copy.deepcopy(carteira_base())


def test_motivo_2_copy_raso_ingenuo_vaza_estado_para_a_original():
    base = carteira_base()
    rasa = copy.copy(base)

    rasa.execute_trade("bitcoin", TradeSide.BUY, Decimal("5"), Decimal("100"))

    # Metade do estado vaza: posições e auditoria são compartilhadas, o caixa não.
    assert base.positions == {"bitcoin": Decimal("15")}
    assert base.cash.value == Decimal("9000")
    assert base.audit_trail is rasa.audit_trail


# ------------------------------------------------------------------ uso no Tournament

def test_todas_as_estrategias_partem_do_mesmo_valor_inicial():
    resultados = Tournament(DEFAULT_ASSET_REGISTRY, historicos_de_teste()).run(CAPITAL)

    assert len(resultados) >= 4
    assert len({r.initial_value_usd for r in resultados}) == 1


def test_torneio_mantem_o_ranking_de_referencia():
    resultados = Tournament(DEFAULT_ASSET_REGISTRY, historicos_de_teste()).run(CAPITAL)

    assert [r.strategy_name for r in resultados] == ["REBALANCEAMENTO", "DCA", "HODL", "STOP-LOSS"]
    assert {r.strategy_name: r.final_value_usd for r in resultados} == {
        "REBALANCEAMENTO": Decimal("14250"),
        "DCA": Decimal("13751.51231537"),
        "HODL": Decimal("13325"),
        "STOP-LOSS": Decimal("11330"),
    }