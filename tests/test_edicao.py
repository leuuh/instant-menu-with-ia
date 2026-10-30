from decimal import Decimal
from typing import Any

import pytest

from core.edicao import (
    CardapioEditado,
    aplicar_edicao,
    formatar_opcoes,
    interpretar_opcoes,
    para_linhas,
)
from core.schema import ExtracaoCardapio, InfoRestaurante, MotivoRevisao, OpcaoPreco

LIMIAR = 0.7
INFO = InfoRestaurante(nome="Teste", telefone=None, horario=None)


def _linhas(json_valido: str) -> list[dict[str, Any]]:
    return para_linhas(ExtracaoCardapio.model_validate_json(json_valido), LIMIAR)


def _aplicar(linhas: list[dict[str, Any]], inferidas: tuple[str, ...] = ()) -> CardapioEditado:
    return aplicar_edicao(linhas, INFO, inferidas, LIMIAR)


def _item(edicao: CardapioEditado, categoria: int, item: int) -> Any:
    assert edicao.cardapio is not None
    return edicao.cardapio.categorias[categoria].itens[item]


def test_para_linhas_tem_uma_linha_por_item(json_valido: str) -> None:
    linhas = _linhas(json_valido)
    assert [linha["nome"] for linha in linhas] == [
        "X-Burguer",
        "X-Salada",
        "Calabresa",
        "Suco de laranja",
    ]
    assert linhas[0]["preco"] == 32.9
    assert linhas[0]["adicionais"] == "Bacon: 4,00"
    assert linhas[0]["alergenicos"] == ["gluten", "lactose", "ovo"]
    assert linhas[0]["alerta"] == ""
    assert linhas[0]["conferido"] is False
    assert linhas[1]["preco"] is None
    assert linhas[1]["alerta"] == "leitura incerta, sem preço"
    assert linhas[2]["variacoes"] == "Média: 45,00; Grande: 58,50"
    assert linhas[2]["adicionais"] == "Borda recheada: ?"


def test_ida_e_volta_preserva_o_cardapio(json_valido: str) -> None:
    original = ExtracaoCardapio.model_validate_json(json_valido)
    edicao = aplicar_edicao(
        para_linhas(original, LIMIAR), original.info_restaurante, ["Bebidas"], LIMIAR
    )
    assert edicao.erros == []
    assert edicao.cardapio == original


def test_pendencias_vem_da_mesma_regra_da_extracao(json_valido: str) -> None:
    pendentes = _aplicar(_linhas(json_valido)).pendencias
    assert [(p.categoria, p.indice_item, p.nome) for p in pendentes] == [
        ("Lanches", 1, "X-Salada"),
        ("Pizzas", 0, "Calabresa"),
        ("Bebidas", 0, "Suco de laranja"),
    ]


def test_conferido_tira_o_item_das_pendencias(json_valido: str) -> None:
    linhas = _linhas(json_valido)
    linhas[1]["conferido"] = True
    edicao = _aplicar(linhas)
    assert "X-Salada" not in [p.nome for p in edicao.pendencias]
    assert _item(edicao, 0, 1).preco is None  # conferir nunca inventa preço


def test_preencher_preco_resolve_so_o_motivo_de_preco(json_valido: str) -> None:
    linhas = _linhas(json_valido)
    linhas[1]["preco"] = 24.5
    edicao = _aplicar(linhas)
    assert _item(edicao, 0, 1).preco == Decimal("24.5")
    pendente = next(p for p in edicao.pendencias if p.nome == "X-Salada")
    assert pendente.motivos == [MotivoRevisao.CONFIANCA_BAIXA]


def test_editar_categoria_agrupa_na_ordem_da_tabela(json_valido: str) -> None:
    linhas = _linhas(json_valido)
    linhas[0]["categoria"] = "Bebidas"
    edicao = _aplicar(linhas)
    assert edicao.cardapio is not None
    assert [c.nome for c in edicao.cardapio.categorias] == ["Bebidas", "Lanches", "Pizzas"]
    assert [i.nome for i in edicao.cardapio.categorias[0].itens] == ["X-Burguer", "Suco de laranja"]


def test_categoria_inferida_so_para_as_informadas(json_valido: str) -> None:
    edicao = _aplicar(_linhas(json_valido), inferidas=("Pizzas",))
    assert edicao.cardapio is not None
    assert {c.nome: c.categoria_inferida for c in edicao.cardapio.categorias} == {
        "Lanches": False,
        "Pizzas": True,
        "Bebidas": False,
    }


def test_excluir_linha_remove_o_item(json_valido: str) -> None:
    edicao = _aplicar(_linhas(json_valido)[1:])
    assert edicao.cardapio is not None
    assert edicao.cardapio.total_itens() == 3


def test_linha_nova_tem_confianca_total_mas_preco_ainda_conta() -> None:
    nova = {"categoria": "Doces", "nome": "Pudim", "preco": None, "confianca": None}
    edicao = _aplicar([nova])
    item = _item(edicao, 0, 0)
    assert item.confianca == 1.0
    assert (item.variacoes, item.alergenicos_provaveis) == ([], [])
    assert edicao.pendencias[0].motivos == [MotivoRevisao.PRECO_AUSENTE]


@pytest.mark.parametrize("vazio", [None, float("nan")])
def test_celulas_vazias_da_tabela_sao_aceitas(vazio: Any) -> None:
    nova = {
        "categoria": "Doces",
        "nome": "Pudim",
        "preco": vazio,
        "variacoes": vazio,
        "adicionais": vazio,
        "descricao": vazio,
        "alergenicos": vazio,
        "confianca": vazio,
        "observacao": vazio,
    }
    item = _item(_aplicar([nova]), 0, 0)
    assert item.preco is None
    assert item.descricao_original is None


def test_alergenicos_aceitam_lista_e_array_da_tabela(json_valido: str) -> None:
    linhas = _linhas(json_valido)
    linhas[0]["alergenicos"] = ("gluten", "soja")
    assert [a.value for a in _item(_aplicar(linhas), 0, 0).alergenicos_provaveis] == [
        "gluten",
        "soja",
    ]


def test_linha_totalmente_vazia_e_ignorada(json_valido: str) -> None:
    edicao = _aplicar([*_linhas(json_valido), {"categoria": None, "nome": None}])
    assert edicao.erros == []
    assert edicao.cardapio is not None
    assert edicao.cardapio.total_itens() == 4


@pytest.mark.parametrize(
    ("campo", "valor", "trecho"),
    [
        ("nome", "", "nome do item"),
        ("categoria", " ", "categoria"),
        ("preco", 0, "maior que zero"),
        ("preco", -3.5, "maior que zero"),
        ("preco", 10.999, "2 casas"),
        ("variacoes", "P 18,00", "nome: preço"),
        ("variacoes", "P: dezoito", "não é um preço válido"),
        ("adicionais", "bacon: 0", "maior que zero"),
    ],
)
def test_edicao_invalida_aponta_a_linha_e_bloqueia(
    json_valido: str, campo: str, valor: Any, trecho: str
) -> None:
    linhas = _linhas(json_valido)
    linhas[2][campo] = valor
    edicao = _aplicar(linhas)
    assert edicao.cardapio is None
    assert edicao.erros[0].linha == 3
    assert edicao.erros[0].item == ("" if campo == "nome" else "Calabresa")
    assert trecho in edicao.erros[0].mensagem


def test_formatar_opcoes_usa_interrogacao_para_preco_desconhecido() -> None:
    opcoes = [
        OpcaoPreco(nome="P", preco=Decimal("18")),
        OpcaoPreco(nome="G", preco=None),
    ]
    assert formatar_opcoes(opcoes) == "P: 18,00; G: ?"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("", []),
        ("P: 18,00; G: ?", [("P", Decimal("18.00")), ("G", None)]),
        ("P: R$ 18,50", [("P", Decimal("18.50"))]),
        ("P: 18.50;", [("P", Decimal("18.50"))]),
        ("Grande: 1.234,50", [("Grande", Decimal("1234.50"))]),
        ("Refri: lata: 6,50", [("Refri: lata", Decimal("6.50"))]),
        ("Média:", [("Média", None)]),
    ],
)
def test_interpretar_opcoes(texto: str, esperado: list[tuple[str, Decimal | None]]) -> None:
    assert [(o.nome, o.preco) for o in interpretar_opcoes(texto)] == esperado
