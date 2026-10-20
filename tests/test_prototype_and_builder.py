"""
Testes do padrão Builder: `PortfolioBuilder` (sem rede).

Cobrem a validação feita antes de a carteira existir, a conversão de pesos em
quantidades e a preservação de RF1, RF6 e RF7 (toda posição entra por
`Portfolio.execute_trade`).
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from crypto_portfolio.assets import DEFAULT_ASSET_REGISTRY
from crypto_portfolio.audit import TradeSide
from crypto_portfolio.errors import AssetNotFoundError, InsufficientBalanceError
from crypto_portfolio.market_data import MarketPoint
from crypto_portfolio.portfolio_builder import PortfolioBuilder
from crypto_portfolio.tournament import Tournament


def ponto(preco):
    return MarketPoint(
        price_usd=Decimal(preco), price_brl=Decimal("0"),
        change_24h_pct=Decimal("0"), market_cap_rank=1,
    )


def snapshot_simples():
    return {"bitcoin": ponto("100"), "ethereum": ponto("50")}


def novo_builder():
    return PortfolioBuilder(DEFAULT_ASSET_REGISTRY)


# ---------------------------------------------------------------- validação

def test_validar_pesos_recusa_soma_fora_do_intervalo_e_peso_negativo():
    with pytest.raises(ValueError, match="deve ficar entre 0 e 1"):
        PortfolioBuilder.validar_pesos({"bitcoin": Decimal("0.6"), "ethereum": Decimal("0.6")})

    with pytest.raises(ValueError, match="não podem ser negativos"):
        PortfolioBuilder.validar_pesos({"bitcoin": Decimal("-0.1"), "ethereum": Decimal("0.3")})


def test_torneio_continua_recusando_pesos_invalidos_na_construcao():
    with pytest.raises(ValueError, match="deve ficar entre 0 e 1"):
        Tournament(DEFAULT_ASSET_REGISTRY, {},
                   initial_weights={"bitcoin": Decimal("0.7"), "ethereum": Decimal("0.7")})

    with pytest.raises(ValueError, match="não podem ser negativos"):
        Tournament(DEFAULT_ASSET_REGISTRY, {},
                   initial_weights={"bitcoin": Decimal("-0.1"), "ethereum": Decimal("0.3")})


def test_build_valida_antes_de_criar_a_carteira():
    builder = (novo_builder().com_caixa_inicial(1000).com_precos(snapshot_simples())
               .com_posicao_por_peso("bitcoin", "0.6").com_posicao_por_peso("ethereum", "0.6"))

    with pytest.raises(ValueError, match="deve ficar entre 0 e 1"):
        builder.build()


def test_pesos_sem_precos_sao_recusados():
    with pytest.raises(ValueError, match="com_precos"):
        novo_builder().com_caixa_inicial(1000).com_posicao_por_peso("bitcoin", "0.5").build()


# ---------------------------------------------------------------- montagem

def test_build_por_peso_converte_pesos_em_quantidades():
    carteira = (novo_builder().com_moeda_base("USD").com_caixa_inicial(10000)
                .com_precos(snapshot_simples())
                .com_posicao_por_peso("bitcoin", "0.35")
                .com_posicao_por_peso("ethereum", "0.35")
                .build())

    assert carteira.base_currency == "USD"
    assert carteira.positions == {"bitcoin": Decimal("35"), "ethereum": Decimal("70")}
    assert carteira.cash.value == Decimal("3000")


def test_ativo_sem_preco_no_snapshot_e_ignorado():
    carteira = (novo_builder().com_caixa_inicial(10000).com_precos({"bitcoin": ponto("100")})
                .com_posicao_por_peso("bitcoin", "0.5")
                .com_posicao_por_peso("ethereum", "0.5")
                .build())

    assert carteira.positions == {"bitcoin": Decimal("50")}
    assert carteira.cash.value == Decimal("5000")


def test_com_posicao_aplica_compras_de_quantidade_fixa():
    carteira = (novo_builder().com_caixa_inicial(10000)
                .com_posicao("bitcoin", 20, 100)
                .com_posicao("ethereum", 40, 50)
                .build())

    assert carteira.positions == {"bitcoin": Decimal("20"), "ethereum": Decimal("40")}
    assert carteira.cash.value == Decimal("6000")


def test_build_devolve_carteiras_independentes():
    builder = novo_builder().com_caixa_inicial(1000)
    primeira, segunda = builder.build(), builder.build()

    assert primeira is not segunda
    assert primeira.audit_trail is not segunda.audit_trail


def test_carteira_montada_pelo_builder_pode_ser_clonada():
    """Builder monta e valida uma vez; Prototype entrega uma cópia independente a cada uso."""
    inicial = novo_builder().com_caixa_inicial(10000).com_posicao("bitcoin", 10, 100).build()
    clone = inicial.clonar()

    clone.execute_trade("bitcoin", TradeSide.SELL, Decimal("10"), Decimal("100"))

    assert clone.positions == {}
    assert inicial.positions == {"bitcoin": Decimal("10")}
    assert inicial.cash.value == Decimal("9000")


# ---------------------------------------------------------------- RF1, RF6 e RF7 preservados

def test_cada_compra_do_builder_fica_na_trilha_de_auditoria():
    carteira = (novo_builder().com_caixa_inicial(10000).com_precos(snapshot_simples())
                .com_posicao_por_peso("bitcoin", "0.35")
                .com_posicao("ethereum", 10, 50)
                .build())

    entradas = carteira.audit_trail.entries
    assert [(t.asset_id, t.side) for t in entradas] == [
        ("bitcoin", TradeSide.BUY), ("ethereum", TradeSide.BUY),
    ]


def test_compra_acima_do_caixa_levanta_erro_especifico_e_nao_devolve_carteira():
    with pytest.raises(InsufficientBalanceError):
        novo_builder().com_caixa_inicial(100).com_posicao("bitcoin", 10, 100).build()


def test_ativo_desconhecido_levanta_erro_especifico():
    with pytest.raises(AssetNotFoundError):
        novo_builder().com_caixa_inicial(100).com_posicao("moeda-inexistente", 1, 1).build()