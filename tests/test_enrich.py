import json
from typing import Any

import pytest

from core.chamada import RespostaInvalidaErro
from core.config import Config
from core.enrich import (
    MAX_CARACTERES,
    ItemParaDescrever,
    gerar_descricoes,
    motivo_para_descartar,
)
from core.providers.fake import ProvedorFake
from core.registro import ARQUIVO_LOG

ITEM = ItemParaDescrever(
    id=0,
    categoria="Lanches",
    nome="X-Frango",
    descricao_original="Pão, frango desfiado e requeijão",
)
SEM_DESCRICAO = ItemParaDescrever(id=1, categoria="Bebidas", nome="Suco de laranja 300ml")


def _resposta(**descricoes: str) -> str:
    return json.dumps(
        {"descricoes": [{"id": int(i[1:]), "descricao": d} for i, d in descricoes.items()]}
    )


def _linhas_log(config: Config) -> list[dict[str, Any]]:
    texto = (config.dir_logs / ARQUIVO_LOG).read_text(encoding="utf-8")
    return [json.loads(linha) for linha in texto.splitlines()]


@pytest.mark.parametrize(
    "sugestao",
    [
        "Pão com frango desfiado e requeijão, uma combinação clássica",
        "PÃES e frango desfiado com muito requeijão",
    ],
)
def test_sugestao_fiel_passa(sugestao: str) -> None:
    assert motivo_para_descartar(sugestao, ITEM) is None


def test_item_sem_descricao_aceita_frase_sobre_o_nome() -> None:
    assert motivo_para_descartar("Suco de laranja de 300ml para refrescar", SEM_DESCRICAO) is None


@pytest.mark.parametrize(
    ("sugestao", "trecho"),
    [
        ("Pão, frango e requeijão com 200g de recheio", "número 200"),
        ("Pão, frango, requeijão e queijo derretido", "queij"),
        ("Pão, frango, requeijão e molho de amendoim", "amendoim"),
        ("Pão artesanal, frango e requeijão", "artesana"),
        ("Pão crocante, frango e requeijão", "crocant"),
        ("Pão, frango e requeijão, feito na hora", "feito na hora"),
        ("Frango desfiado e requeijão", "omitiu 'pao'"),
        ("Pão com frango desfiado", "omitiu 'requeij'"),
        ("Pão, frango e requeijão. " + "muito bom " * 20, "caracteres"),
    ],
)
def test_sugestao_que_muda_o_prato_e_descartada(sugestao: str, trecho: str) -> None:
    motivo = motivo_para_descartar(sugestao, ITEM)
    assert motivo is not None
    assert trecho in motivo


def test_limite_de_caracteres_aceita_o_valor_exato() -> None:
    sugestao = ("Pão, frango e requeijão " * 10)[:MAX_CARACTERES]
    assert motivo_para_descartar(sugestao, ITEM) is None


def test_gera_sugestoes_sem_enviar_imagem(config: Config) -> None:
    provedor = ProvedorFake(
        [_resposta(i0="Pão com frango desfiado e requeijão", i1="Suco de laranja para refrescar")]
    )
    resultado = gerar_descricoes([ITEM, SEM_DESCRICAO], provedor, config)

    assert resultado.sugestoes == {
        0: "Pão com frango desfiado e requeijão",
        1: "Suco de laranja para refrescar",
    }
    assert resultado.descartadas == {}
    chamada = provedor.chamadas[0]
    assert chamada.midias == []
    assert "## REGRAS" in chamada.instrucoes
    assert '"nome": "X-Frango"' in chamada.instrucoes
    assert "$ref" not in json.dumps(chamada.schema)


def test_descarta_a_invencao_e_mantem_as_outras(config: Config) -> None:
    provedor = ProvedorFake(
        [_resposta(i0="Pão, frango, requeijão e bacon com 2 ovos", i1="Suco de laranja gelado")]
    )
    resultado = gerar_descricoes([ITEM, SEM_DESCRICAO], provedor, config)

    assert list(resultado.sugestoes) == [1]
    assert "número 2" in resultado.descartadas[0]


def test_ignora_id_desconhecido_e_tolera_id_ausente(config: Config) -> None:
    provedor = ProvedorFake([_resposta(i99="Texto qualquer")])
    resultado = gerar_descricoes([ITEM], provedor, config)
    assert (resultado.sugestoes, resultado.descartadas) == ({}, {})


def test_resposta_invalida_gera_correcao(config: Config) -> None:
    valida = _resposta(i0="Pão com frango desfiado e requeijão")
    provedor = ProvedorFake(['{"descricoes": [{"id": -1, "descricao": "x"}]}', valida])
    assert 0 in gerar_descricoes([ITEM], provedor, config).sugestoes
    assert provedor.chamadas[1].correcoes[0].mensagem_erro


def test_desiste_apos_as_correcoes(config: Config) -> None:
    with pytest.raises(RespostaInvalidaErro):
        gerar_descricoes([ITEM], ProvedorFake(["não é json"] * 3), config)


def test_log_e_metricas(config: Config) -> None:
    provedor = ProvedorFake(
        [_resposta(i0="Pão, frango, requeijão e queijo")],
        modelo="gemini-3.5-flash-lite",
    )
    resultado = gerar_descricoes([ITEM], provedor, config)

    assert resultado.metricas.custo_estimado_usd is not None
    log = _linhas_log(config)[-1]
    assert log["tipo"] == "descricoes"
    assert (log["n_itens"], log["n_sugestoes"], log["n_descartadas"]) == (1, 0, 1)


def test_config_para_descricoes_usa_o_modelo_proprio(config: Config) -> None:
    config = config.model_copy(update={"llm_model": "leve", "llm_model_descricoes": "forte"})
    assert config.para_descricoes().llm_model == "forte"
    assert config.llm_model == "leve"


def test_config_para_descricoes_sem_modelo_proprio_usa_o_da_extracao(config: Config) -> None:
    config = config.model_copy(update={"llm_model": "leve", "llm_model_descricoes": None})
    assert config.para_descricoes().llm_model == "leve"
