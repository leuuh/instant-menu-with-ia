import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from core.schema import Alergenico, ExtracaoCardapio, schema_para_llm


def _primeiro_item(dados: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = dados["categorias"][0]["itens"][0]
    return item


def test_fixture_valida_e_aceita(json_valido: str) -> None:
    cardapio = ExtracaoCardapio.model_validate_json(json_valido)
    assert cardapio.total_itens() == 4
    assert cardapio.categorias[2].categoria_inferida is True


def test_preco_mantem_valor_exato_como_decimal(json_valido: str) -> None:
    item = ExtracaoCardapio.model_validate_json(json_valido).categorias[0].itens[0]
    assert item.preco == Decimal("32.90")
    assert item.alergenicos_provaveis == [Alergenico.GLUTEN, Alergenico.LACTOSE, Alergenico.OVO]


def test_exportacao_json_tem_preco_como_numero(json_valido: str) -> None:
    exportado = json.loads(ExtracaoCardapio.model_validate_json(json_valido).model_dump_json())
    assert _primeiro_item(exportado)["preco"] == 32.9
    assert isinstance(_primeiro_item(exportado)["preco"], float)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("preco", 0),
        ("preco", -5),
        ("preco", 10.999),
        ("confianca", 1.2),
        ("confianca", -0.1),
        ("nome", ""),
        ("alergenicos_provaveis", ["pimenta"]),
    ],
)
def test_valores_invalidos_sao_rejeitados(
    dados_validos: dict[str, Any], campo: str, valor: Any
) -> None:
    _primeiro_item(dados_validos)[campo] = valor
    with pytest.raises(ValidationError):
        ExtracaoCardapio.model_validate(dados_validos)


def test_campo_extra_e_rejeitado(dados_validos: dict[str, Any]) -> None:
    _primeiro_item(dados_validos)["preco_promocional"] = 10
    with pytest.raises(ValidationError):
        ExtracaoCardapio.model_validate(dados_validos)


def test_campo_obrigatorio_ausente_e_rejeitado(dados_validos: dict[str, Any]) -> None:
    del _primeiro_item(dados_validos)["observacao"]
    with pytest.raises(ValidationError):
        ExtracaoCardapio.model_validate(dados_validos)


def test_schema_para_llm_nao_tem_referencias_nem_anyof() -> None:
    texto = json.dumps(schema_para_llm(ExtracaoCardapio))
    assert "$ref" not in texto
    assert "$defs" not in texto
    assert "anyOf" not in texto


def test_schema_para_llm_representa_nulo_como_array_de_tipos() -> None:
    schema = schema_para_llm(ExtracaoCardapio)
    item = schema["properties"]["categorias"]["items"]["properties"]["itens"]["items"]
    assert item["properties"]["preco"]["type"] == ["number", "null"]
    assert item["properties"]["confianca"]["minimum"] == 0
    assert item["properties"]["confianca"]["maximum"] == 1
    assert item["properties"]["alergenicos_provaveis"]["items"]["enum"] == [
        a.value for a in Alergenico
    ]
    assert item["additionalProperties"] is False
