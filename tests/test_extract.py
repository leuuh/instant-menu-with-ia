import json
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from core.arquivos import Entrada
from core.chamada import RespostaInvalidaErro
from core.config import Config
from core.extract import extrair_cardapio, extrair_entradas
from core.precos import calcular_custo
from core.providers.base import Midia, ProvedorErro
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
    with pytest.raises(RespostaInvalidaErro) as excinfo:
        extrair_cardapio(foto, provedor, config)

    assert excinfo.value.metricas.tentativas == 3
    assert len(provedor.chamadas) == 3
    assert len(provedor.chamadas[2].correcoes) == 2
    log = _linhas_log(config)[-1]
    assert log["sucesso"] is False
    assert log["erro"].startswith("RespostaInvalidaErro")


def test_max_correcoes_zero_faz_uma_chamada(foto: Path, config: Config) -> None:
    config = config.model_copy(update={"max_correcoes": 0})
    provedor = ProvedorFake([JSON_INCOMPLETO])
    with pytest.raises(RespostaInvalidaErro):
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


def _entrada(nome: str) -> Entrada:
    return Entrada(nome, Midia(dados=nome.encode(), mime="image/jpeg"))


def _json_com_itens(*itens: tuple[str, float]) -> str:
    return json.dumps(
        {
            "info_restaurante": {"nome": None, "telefone": None, "horario": None},
            "categorias": [
                {
                    "nome": "Lanches",
                    "categoria_inferida": False,
                    "itens": [
                        {
                            "nome": nome,
                            "descricao_original": None,
                            "preco": preco,
                            "variacoes": [],
                            "adicionais": [],
                            "alergenicos_provaveis": [],
                            "confianca": 0.95,
                            "observacao": None,
                        }
                        for nome, preco in itens
                    ],
                }
            ],
        }
    )


def _responder_por_arquivo(
    respostas: dict[str, str | Exception],
) -> Callable[[Sequence[Midia]], str]:
    def responder(midias: Sequence[Midia]) -> str:
        resposta = respostas[midias[0].dados.decode()]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return responder


def test_varias_fotos_sao_lidas_uma_a_uma_e_unidas(config: Config) -> None:
    provedor = ProvedorFake(
        responder=_responder_por_arquivo(
            {
                "a.jpg": _json_com_itens(("X-Tudo", 20.0), ("Misto", 12.0)),
                "b.jpg": _json_com_itens(("Misto", 12.0), ("Suco", 9.0)),
            }
        )
    )
    resultado = extrair_entradas([_entrada("a.jpg"), _entrada("b.jpg")], provedor, config)

    assert [i.nome for i in resultado.cardapio.categorias[0].itens] == ["X-Tudo", "Misto", "Suco"]
    assert len(provedor.chamadas) == 2
    assert all(len(chamada.midias) == 1 for chamada in provedor.chamadas)
    assert resultado.avisos == []


def test_metricas_somam_e_detalham_cada_arquivo(config: Config) -> None:
    provedor = ProvedorFake(
        modelo="gemini-3.5-flash-lite",
        responder=_responder_por_arquivo(
            {"a.jpg": _json_com_itens(("X-Tudo", 20.0)), "b.jpg": _json_com_itens(("Suco", 9.0))}
        ),
    )
    metricas = extrair_entradas([_entrada("a.jpg"), _entrada("b.jpg")], provedor, config).metricas

    assert (metricas.tokens_entrada, metricas.tokens_saida, metricas.tentativas) == (2000, 1000, 2)
    assert metricas.custo_estimado_usd == calcular_custo("gemini-3.5-flash-lite", 2000, 1000)
    assert [(a.nome, a.itens, a.tentativas) for a in metricas.arquivos] == [
        ("a.jpg", 1, 1),
        ("b.jpg", 1, 1),
    ]
    log = _linhas_log(config)[-1]
    assert log["origem"] == "a.jpg, b.jpg"
    assert log["tipo"] == "extracao"
    assert len(log["arquivos"]) == 2


def test_arquivo_que_falha_vira_aviso_e_nao_derruba_os_outros(config: Config) -> None:
    provedor = ProvedorFake(
        responder=_responder_por_arquivo(
            {"a.jpg": _json_com_itens(("X-Tudo", 20.0)), "b.jpg": ProvedorErro("cota esgotada")}
        )
    )
    resultado = extrair_entradas([_entrada("a.jpg"), _entrada("b.jpg")], provedor, config)

    assert resultado.cardapio.total_itens() == 1
    assert "b.jpg: não foi possível ler" in resultado.avisos[0]
    assert "cota esgotada" in resultado.avisos[0]
    assert resultado.metricas.arquivos[1].erro == "cota esgotada"
    log = _linhas_log(config)[-1]
    assert (log["sucesso"], log["n_avisos"]) == (True, 1)


def test_todos_os_arquivos_falham(config: Config) -> None:
    provedor = ProvedorFake(
        responder=_responder_por_arquivo(
            {"a.jpg": ProvedorErro("cota esgotada"), "b.jpg": ProvedorErro("outro erro")}
        )
    )
    with pytest.raises(ProvedorErro, match="cota esgotada"):
        extrair_entradas([_entrada("a.jpg"), _entrada("b.jpg")], provedor, config)
    assert _linhas_log(config)[-1]["sucesso"] is False


def test_foto_sem_itens_gera_aviso_quando_ha_outras(config: Config) -> None:
    provedor = ProvedorFake(
        responder=_responder_por_arquivo(
            {"a.jpg": _json_com_itens(("X-Tudo", 20.0)), "b.jpg": _json_com_itens()}
        )
    )
    resultado = extrair_entradas([_entrada("a.jpg"), _entrada("b.jpg")], provedor, config)
    assert resultado.avisos == ["b.jpg: nenhum item encontrado nesse arquivo."]


def test_arquivos_sao_lidos_em_paralelo(config: Config) -> None:
    barreira = threading.Barrier(2, timeout=10)

    def responder(_midias: Sequence[Midia]) -> str:
        barreira.wait()  # só passa se as duas chamadas estiverem acontecendo ao mesmo tempo
        return _json_com_itens(("X-Tudo", 20.0))

    provedor = ProvedorFake(responder=responder)
    resultado = extrair_entradas([_entrada("a.jpg"), _entrada("b.jpg")], provedor, config)
    assert resultado.cardapio.total_itens() == 1


def test_limite_de_chamadas_paralelas(config: Config) -> None:
    config = config.model_copy(update={"max_chamadas_paralelas": 1})
    ordem: list[str] = []

    def responder(midias: Sequence[Midia]) -> str:
        ordem.append(midias[0].dados.decode())
        return _json_com_itens(("X-Tudo", 20.0))

    extrair_entradas(
        [_entrada("a.jpg"), _entrada("b.jpg"), _entrada("c.jpg")],
        ProvedorFake(responder=responder),
        config,
    )
    assert ordem == ["a.jpg", "b.jpg", "c.jpg"]
