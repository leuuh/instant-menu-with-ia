import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from core.config import Config
from core.extract import ExtracaoInvalidaErro, extrair_cardapio
from core.precos import calcular_custo
from core.providers.base import ProvedorErro
from core.providers.fake import ProvedorFake
from core.registro import ARQUIVO_LOG

JSON_INCOMPLETO = '{"info_restaurante": {"nome": null, "telefone": null}, "categorias": []}'


@pytest.fixture
def foto(tmp_path: Path) -> Path:
    caminho = tmp_path / "cardapio.png"
    Image.new("RGB", (600, 800), "white").save(caminho)
    return caminho


def _linhas_log(config: Config) -> list[dict[str, Any]]:
    texto = (config.dir_logs / ARQUIVO_LOG).read_text(encoding="utf-8")
    return [json.loads(linha) for linha in texto.splitlines()]


def test_sucesso_na_primeira_tentativa(foto: Path, config: Config, json_valido: str) -> None:
    provedor = ProvedorFake([json_valido])
    resultado = extrair_cardapio(foto, provedor, config)

    assert resultado.cardapio.total_itens() == 4
    assert len(resultado.revisao) == 3
    assert resultado.metricas.tentativas == 1
    chamada = provedor.chamadas[0]
    assert chamada.midias[0].mime == "image/jpeg"
    assert "## REGRAS" in chamada.instrucoes
    assert "$ref" not in json.dumps(chamada.schema)
    assert chamada.correcoes == []


def test_json_invalido_e_corrigido_com_erro_enviado_ao_modelo(
    foto: Path, config: Config, json_valido: str
) -> None:
    provedor = ProvedorFake([JSON_INCOMPLETO, json_valido])
    resultado = extrair_cardapio(foto, provedor, config)

    assert resultado.metricas.tentativas == 2
    correcao = provedor.chamadas[1].correcoes[0]
    assert correcao.resposta_anterior == JSON_INCOMPLETO
    assert "info_restaurante.horario: Field required" in correcao.mensagem_erro
    assert "{erros}" not in correcao.mensagem_erro


def test_preco_zero_gera_correcao(
    foto: Path, config: Config, json_valido: str, dados_validos: dict[str, Any]
) -> None:
    dados_validos["categorias"][0]["itens"][0]["preco"] = 0
    provedor = ProvedorFake([json.dumps(dados_validos), json_valido])
    extrair_cardapio(foto, provedor, config)

    mensagem = provedor.chamadas[1].correcoes[0].mensagem_erro
    assert "categorias.0.itens.0.preco: Input should be greater than 0" in mensagem


def test_texto_fora_do_json_gera_correcao(foto: Path, config: Config, json_valido: str) -> None:
    provedor = ProvedorFake(["Aqui está o cardápio: {}", json_valido])
    assert extrair_cardapio(foto, provedor, config).metricas.tentativas == 2
    assert "Invalid JSON" in provedor.chamadas[1].correcoes[0].mensagem_erro


def test_falha_apos_duas_correcoes(foto: Path, config: Config) -> None:
    provedor = ProvedorFake([JSON_INCOMPLETO] * 3)
    with pytest.raises(ExtracaoInvalidaErro) as excinfo:
        extrair_cardapio(foto, provedor, config)

    assert excinfo.value.metricas.tentativas == 3
    assert len(provedor.chamadas) == 3
    assert len(provedor.chamadas[2].correcoes) == 2
    log = _linhas_log(config)[-1]
    assert log["sucesso"] is False
    assert log["erro"].startswith("ExtracaoInvalidaErro")


def test_max_correcoes_zero_faz_uma_chamada(foto: Path, config: Config) -> None:
    config = config.model_copy(update={"max_correcoes": 0})
    provedor = ProvedorFake([JSON_INCOMPLETO])
    with pytest.raises(ExtracaoInvalidaErro):
        extrair_cardapio(foto, provedor, config)
    assert len(provedor.chamadas) == 1


def test_tokens_e_custo_somam_todas_as_tentativas(
    foto: Path, config: Config, json_valido: str
) -> None:
    provedor = ProvedorFake(
        [JSON_INCOMPLETO, json_valido],
        modelo="gemini-3.8-flash",
        tokens_entrada=1000,
        tokens_saida=500,
    )
    metricas = extrair_cardapio(foto, provedor, config).metricas

    assert (metricas.tokens_entrada, metricas.tokens_saida) == (2000, 1000)
    assert metricas.custo_estimado_usd == calcular_custo("gemini-3.8-flash", 2000, 1000)
    assert metricas.custo_estimado_usd is not None


def test_log_registra_metricas_da_extracao(foto: Path, config: Config, json_valido: str) -> None:
    extrair_cardapio(foto, ProvedorFake([json_valido]), config)

    log = _linhas_log(config)[-1]
    assert log["sucesso"] is True
    assert log["origem"] == "cardapio.png"
    assert log["provedor"] == "fake"
    assert log["modelo"] == "fake-modelo"
    assert (log["n_itens"], log["n_revisao"], log["tentativas"]) == (4, 3, 1)
    assert len(log["prompt_sha"]) == 8
    assert {"timestamp", "tokens_entrada", "tokens_saida", "custo_estimado_usd", "tempo_s"} <= set(
        log
    )


def test_erro_do_provedor_e_registrado_e_propagado(foto: Path, config: Config) -> None:
    with pytest.raises(ProvedorErro):
        extrair_cardapio(foto, ProvedorFake([]), config)
    assert _linhas_log(config)[-1]["sucesso"] is False
