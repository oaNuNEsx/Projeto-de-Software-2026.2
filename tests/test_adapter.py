"""
Testes do padrão Adapter: `PriceAdapter`, `CoinGeckoAdapter`, `StaticDataAdapter` e a
injeção do adaptador no `PriceService` (sem rede).

Antes do Adapter, o `PriceService` só podia ser exercitado com a CoinGecko ao vivo, então
o cache e a deduplicação do RF8 não tinham teste automatizado. Com o adaptador, eles
passam a ser verificáveis offline.
"""
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import requests

from crypto_portfolio import market_data
from crypto_portfolio.errors import RateLimitExceededError
from crypto_portfolio.market_data import (
    CoinGeckoAdapter,
    MarketPoint,
    PriceAdapter,
    PriceService,
    StaticDataAdapter,
)


# ---------------------------------------------------------------- apoio

def ponto(preco, brl="0", variacao="0", rank=1):
    return MarketPoint(
        price_usd=Decimal(preco), price_brl=Decimal(brl),
        change_24h_pct=Decimal(variacao), market_cap_rank=rank,
    )


class AdaptadorContador(PriceAdapter):
    """Adaptador de teste: devolve pontos fixos e anota cada pedido recebido."""

    def __init__(self, dados):
        self._dados = dados
        self.pedidos = []

    def fetch_market_data(self, coin_ids):
        self.pedidos.append(list(coin_ids))
        return {cid: self._dados[cid] for cid in coin_ids if cid in self._dados}


class AdaptadorQuebrado(PriceAdapter):
    """Falha na primeira chamada e funciona nas seguintes."""

    def __init__(self):
        self.chamadas = 0

    def fetch_market_data(self, coin_ids):
        self.chamadas += 1
        if self.chamadas == 1:
            raise requests.ConnectionError("sem rede")
        return {cid: ponto("100") for cid in coin_ids}


class RespostaFalsa:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class SessaoFalsa:
    """Responde na ordem de um roteiro e anota cada requisição (URL e parâmetros)."""

    def __init__(self, roteiro):
        self._roteiro = list(roteiro)
        self.chamadas = []

    def get(self, url, params=None, timeout=None):
        self.chamadas.append((url, dict(params or {})))
        assert self._roteiro, "a sessão falsa recebeu mais requisições que o roteiro previa"
        return self._roteiro.pop(0)


class LimitadorFalso:
    def __init__(self):
        self.consultas = 0

    def acquire(self):
        self.consultas += 1


class RelogioFalso:
    """Substitui o módulo `time` SÓ dentro de market_data: registra as esperas em vez de dormir."""

    monotonic = staticmethod(time.monotonic)

    def __init__(self):
        self.esperas = []

    def sleep(self, segundos):
        self.esperas.append(segundos)


@pytest.fixture
def relogio(monkeypatch):
    falso = RelogioFalso()
    monkeypatch.setattr(market_data, "time", falso)
    return falso


def item(cid, preco=100, variacao=1.5, rank=1):
    return {"id": cid, "current_price": preco, "price_change_percentage_24h": variacao,
            "market_cap_rank": rank}


def mercado(*itens):
    return RespostaFalsa(payload=list(itens))


def brl(**precos):
    return RespostaFalsa(payload={cid: {"brl": valor} for cid, valor in precos.items()})


# ---------------------------------------------------------------- PriceService com adaptadores

def test_price_service_busca_os_precos_pelo_adaptador():
    btc = ponto("60000")
    servico = PriceService(adapter=StaticDataAdapter({"bitcoin": btc}))

    assert servico.get_prices(["bitcoin"])["bitcoin"] is btc


def test_id_que_o_adaptador_nao_conhece_fica_fora_do_resultado():
    servico = PriceService(adapter=StaticDataAdapter({"bitcoin": ponto("60000")}))

    assert list(servico.get_prices(["bitcoin", "moeda-inexistente"])) == ["bitcoin"]


def test_tres_consumidores_pedindo_o_mesmo_preco_geram_uma_unica_busca():
    """É a garantia do RF8 ('3 estratégias, 1 chamada'), agora verificável sem internet."""
    adaptador = AdaptadorContador({"bitcoin": ponto("60000")})
    servico = PriceService(cache_ttl=1000.0, adapter=adaptador)

    for _ in range(3):
        servico.get_prices(["bitcoin"])

    assert adaptador.pedidos == [["bitcoin"]]


def test_ids_repetidos_e_fora_de_ordem_chegam_ao_adaptador_deduplicados_e_ordenados():
    adaptador = AdaptadorContador({"bitcoin": ponto("1"), "tether": ponto("1")})
    servico = PriceService(adapter=adaptador)

    servico.get_prices(["tether", "bitcoin", "bitcoin"])

    assert adaptador.pedidos == [["bitcoin", "tether"]]


def test_so_os_ids_fora_do_cache_vao_ao_adaptador():
    adaptador = AdaptadorContador({"bitcoin": ponto("1"), "ethereum": ponto("1")})
    servico = PriceService(cache_ttl=1000.0, adapter=adaptador)

    servico.get_prices(["bitcoin"])
    servico.get_prices(["bitcoin", "ethereum"])

    assert adaptador.pedidos == [["bitcoin"], ["ethereum"]]


def test_cache_expirado_busca_de_novo():
    adaptador = AdaptadorContador({"bitcoin": ponto("1")})
    servico = PriceService(cache_ttl=0.0, adapter=adaptador)

    servico.get_prices(["bitcoin"])
    servico.get_prices(["bitcoin"])

    assert adaptador.pedidos == [["bitcoin"], ["bitcoin"]]


def test_falha_do_adaptador_sobe_e_nada_entra_no_cache():
    adaptador = AdaptadorQuebrado()
    servico = PriceService(cache_ttl=1000.0, adapter=adaptador)

    with pytest.raises(requests.ConnectionError):
        servico.get_prices(["bitcoin"])

    assert "bitcoin" in servico.get_prices(["bitcoin"])
    assert adaptador.chamadas == 2


def test_adaptador_estatico_nao_e_afetado_por_mudancas_no_dicionario_original():
    dados = {"bitcoin": ponto("60000")}
    adaptador = StaticDataAdapter(dados)

    dados["ethereum"] = ponto("3000")

    assert list(adaptador.fetch_market_data(["bitcoin", "ethereum"])) == ["bitcoin"]


def test_a_interface_do_adaptador_e_abstrata():
    with pytest.raises(TypeError):
        PriceAdapter()


# ---------------------------------------------------------------- construtor do PriceService

def test_construtor_antigo_continua_funcionando():
    """Sem `adapter`, o PriceService usa um CoinGeckoAdapter (comportamento de antes)."""
    sessao = SessaoFalsa([mercado(item("bitcoin", 60000.5, 1.25, 1)), brl(bitcoin=300000)])
    servico = PriceService(cache_ttl=30.0, max_calls_per_minute=10, session=sessao)

    preco = servico.get_prices(["bitcoin"])["bitcoin"]

    assert preco == ponto("60000.5", "300000", "1.25", 1)


def test_sessao_e_adaptador_juntos_sao_recusados():
    with pytest.raises(ValueError, match="session"):
        PriceService(session=SessaoFalsa([]), adapter=StaticDataAdapter({}))


# ---------------------------------------------------------------- CoinGeckoAdapter

def test_traduz_o_json_da_coingecko_para_market_point():
    sessao = SessaoFalsa([
        mercado(item("bitcoin", 60000.5, 1.25, 1), item("ethereum", 3000, -2.5, 2)),
        brl(bitcoin=300000, ethereum=15000),
    ])
    adaptador = CoinGeckoAdapter(session=sessao, limiter=LimitadorFalso())

    pontos = adaptador.fetch_market_data(["bitcoin", "ethereum"])

    assert pontos == {
        "bitcoin": ponto("60000.5", "300000", "1.25", 1),
        "ethereum": ponto("3000", "15000", "-2.5", 2),
    }
    (url_usd, params_usd), (url_brl, params_brl) = sessao.chamadas
    assert url_usd.endswith("/coins/markets")
    assert params_usd == {"vs_currency": "usd", "ids": "bitcoin,ethereum", "price_change_percentage": "24h"}
    assert url_brl.endswith("/simple/price")
    assert params_brl == {"ids": "bitcoin,ethereum", "vs_currencies": "brl"}


def test_conversoes_com_perda_documentadas():
    sessao = SessaoFalsa([
        mercado(
            {"id": "bitcoin", "current_price": None, "price_change_percentage_24h": None,
             "market_cap_rank": None},
            {"id": "ethereum", "current_price": 3000},
        ),
        RespostaFalsa(payload={"bitcoin": {}}),
    ])
    adaptador = CoinGeckoAdapter(session=sessao, limiter=LimitadorFalso())

    pontos = adaptador.fetch_market_data(["bitcoin", "ethereum"])

    # preço/variação nulos viram 0; rank ausente vira 9999; BRL ausente vira 0
    assert pontos["bitcoin"] == ponto("0", "0", "0", 9999)
    assert pontos["ethereum"] == ponto("3000", "0", "0", 9999)


def test_cada_requisicao_http_consulta_o_limitador():
    """Por isso o limitador mora no adaptador: cada busca faz DUAS requisições (USD e BRL)."""
    limitador = LimitadorFalso()
    sessao = SessaoFalsa([mercado(item("bitcoin")), brl(bitcoin=1)])

    CoinGeckoAdapter(session=sessao, limiter=limitador).fetch_market_data(["bitcoin"])

    assert len(sessao.chamadas) == 2
    assert limitador.consultas == 2


def test_http_429_com_retry_after_espera_o_tempo_pedido_e_tenta_de_novo(relogio):
    limitador = LimitadorFalso()
    sessao = SessaoFalsa([
        RespostaFalsa(429, headers={"Retry-After": "3"}),
        mercado(item("bitcoin")), brl(bitcoin=1),
    ])

    pontos = CoinGeckoAdapter(session=sessao, limiter=limitador).fetch_market_data(["bitcoin"])

    assert "bitcoin" in pontos
    assert relogio.esperas == [3.0]
    assert limitador.consultas == 3  # o limitador também conta a tentativa que recebeu 429


def test_http_429_sem_retry_after_usa_backoff_exponencial(relogio):
    sessao = SessaoFalsa([
        RespostaFalsa(429), RespostaFalsa(429),
        mercado(item("bitcoin")), brl(bitcoin=1),
    ])

    CoinGeckoAdapter(session=sessao, limiter=LimitadorFalso()).fetch_market_data(["bitcoin"])

    assert relogio.esperas == [2.0, 4.0]


def test_http_429_repetido_levanta_erro_especifico(relogio):
    sessao = SessaoFalsa([RespostaFalsa(429)] * 6)
    adaptador = CoinGeckoAdapter(session=sessao, limiter=LimitadorFalso())

    with pytest.raises(RateLimitExceededError):
        adaptador.fetch_market_data(["bitcoin"])

    assert relogio.esperas == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_erro_http_sobe_como_http_error():
    sessao = SessaoFalsa([RespostaFalsa(500)])

    with pytest.raises(requests.HTTPError):
        CoinGeckoAdapter(session=sessao, limiter=LimitadorFalso()).fetch_market_data(["bitcoin"])