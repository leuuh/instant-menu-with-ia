from decimal import Decimal
from typing import Any

from core.revisao import itens_para_revisao
from core.schema import (
    CategoriaExtraida,
    ExtracaoCardapio,
    InfoRestaurante,
    ItemExtraido,
    MotivoRevisao,
    OpcaoPreco,
)
from core.unir import normalizar, unir_cardapios


def _item(
    nome: str, preco: str | None = "10.00", confianca: float = 0.95, **extras: Any
) -> ItemExtraido:
    dados: dict[str, Any] = {
        "nome": nome,
        "descricao_original": None,
        "preco": Decimal(preco) if preco else None,
        "variacoes": [],
        "adicionais": [],
        "alergenicos_provaveis": [],
        "confianca": confianca,
        "observacao": None,
        **extras,
    }
    return ItemExtraido(**dados)


def _cardapio(
    *categorias: tuple[str, list[ItemExtraido]], inferida: bool = False
) -> ExtracaoCardapio:
    return ExtracaoCardapio(
        info_restaurante=InfoRestaurante(nome=None, telefone=None, horario=None),
        categorias=[
            CategoriaExtraida(nome=nome, categoria_inferida=inferida, itens=itens)
            for nome, itens in categorias
        ],
    )


def _nomes(cardapio: ExtracaoCardapio) -> list[tuple[str, str]]:
    return [(c.nome, i.nome) for c in cardapio.categorias for i in c.itens]


def test_um_cardapio_volta_sem_alteracao() -> None:
    cardapio = _cardapio(("Lanches", [_item("X-Tudo"), _item("X-Tudo")]))
    assert unir_cardapios([cardapio]) is cardapio


def test_remove_item_repetido_entre_fotos_mantendo_a_ordem() -> None:
    a = _cardapio(("Lanches", [_item("X-Tudo"), _item("X-Salada")]))
    b = _cardapio(("Lanches", [_item("X-Salada"), _item("Misto")]), ("Bebidas", [_item("Suco")]))
    assert _nomes(unir_cardapios([a, b])) == [
        ("Lanches", "X-Tudo"),
        ("Lanches", "X-Salada"),
        ("Lanches", "Misto"),
        ("Bebidas", "Suco"),
    ]


def test_ignora_acento_caixa_e_pontuacao() -> None:
    a = _cardapio(("BEBIDAS", [_item("Água com gás")]))
    b = _cardapio(("Bebidas", [_item("agua com gas.")]))
    assert _nomes(unir_cardapios([a, b])) == [("BEBIDAS", "Água com gás")]


def test_normalizar() -> None:
    assert normalizar(" X-Búrguer! (6 un.) ") == "x burguer 6 un"


def test_mesmo_nome_em_categorias_explicitas_sao_itens_diferentes() -> None:
    a = _cardapio(("Sanduíches", [_item("Bacon", "3.60")]))
    b = _cardapio(("Sanduíches na chapa", [_item("Bacon", "3.60")]))
    assert len(_nomes(unir_cardapios([a, b]))) == 2


def test_categoria_deduzida_une_com_outra_quando_o_preco_bate() -> None:
    a = _cardapio(("Lanches clássicos", [_item("X-Tudo")]))
    b = _cardapio(("Lanches", [_item("X-Tudo"), _item("Misto")]), inferida=True)
    assert _nomes(unir_cardapios([a, b])) == [
        ("Lanches clássicos", "X-Tudo"),
        ("Lanches", "Misto"),
    ]


def test_categoria_deduzida_nao_une_quando_o_preco_diverge() -> None:
    a = _cardapio(("Lanches clássicos", [_item("X-Tudo", "10.00")]))
    b = _cardapio(("Lanches", [_item("X-Tudo", "12.00")]), inferida=True)
    assert len(_nomes(unir_cardapios([a, b]))) == 2


def test_categoria_explicita_substitui_a_deduzida() -> None:
    a = _cardapio(("bebidas", [_item("Suco")]), inferida=True)
    b = _cardapio(("Bebidas", [_item("Água")]))
    categoria = unir_cardapios([a, b]).categorias[0]
    assert (categoria.nome, categoria.categoria_inferida) == ("Bebidas", False)


def test_preco_divergente_vira_null_e_vai_para_revisao() -> None:
    a = _cardapio(("Lanches", [_item("X-Tudo", "9.50", confianca=0.95)]))
    b = _cardapio(("Lanches", [_item("X-Tudo", "8.99", confianca=0.9)]))
    unido = unir_cardapios([a, b])
    item = unido.categorias[0].itens[0]

    assert item.preco is None
    assert item.observacao == "Preço do item: as fotos mostram 9,50 e 8,99"
    assert item.confianca == 0.9
    assert itens_para_revisao(unido, 0.5)[0].motivos == [MotivoRevisao.PRECO_AUSENTE]


def test_foto_legivel_completa_a_que_nao_tinha_preco() -> None:
    a = _cardapio(("Lanches", [_item("X-Tudo", None, confianca=0.3, observacao="Borrado")]))
    b = _cardapio(("Lanches", [_item("X-Tudo", "9.50", confianca=0.9)]))
    item = unir_cardapios([a, b]).categorias[0].itens[0]
    assert (item.preco, item.confianca) == (Decimal("9.50"), 0.9)
    assert item.observacao == "Borrado"


def test_confianca_e_a_da_leitura_que_trouxe_o_preco() -> None:
    a = _cardapio(("Lanches", [_item("X-Tudo", "9.50", confianca=0.5)]))
    b = _cardapio(("Lanches", [_item("X-Tudo", None, confianca=0.99)]))
    assert unir_cardapios([a, b]).categorias[0].itens[0].confianca == 0.5


def test_duas_leituras_iguais_ficam_com_a_maior_confianca() -> None:
    a = _cardapio(("Lanches", [_item("X-Tudo", confianca=0.6)]))
    b = _cardapio(("Lanches", [_item("X-Tudo", confianca=0.9)]))
    assert unir_cardapios([a, b]).categorias[0].itens[0].confianca == 0.9


def test_une_variacoes_e_anula_a_que_diverge() -> None:
    def opcoes(**precos: str) -> list[OpcaoPreco]:
        return [OpcaoPreco(nome=n, preco=Decimal(p)) for n, p in precos.items()]

    a = _cardapio(("Pizzas", [_item("Calabresa", None, variacoes=opcoes(P="30.00", G="50.00"))]))
    b = _cardapio(("Pizzas", [_item("Calabresa", None, variacoes=opcoes(G="55.00", M="40.00"))]))
    unido = unir_cardapios([a, b])
    item = unido.categorias[0].itens[0]

    assert [(v.nome, v.preco) for v in item.variacoes] == [
        ("P", Decimal("30.00")),
        ("G", None),
        ("M", Decimal("40.00")),
    ]
    assert item.observacao == "G: as fotos mostram 50,00 e 55,00"
    assert MotivoRevisao.PRECO_VARIACAO_AUSENTE in itens_para_revisao(unido, 0.5)[0].motivos


def test_une_adicionais_alergenicos_e_descricao() -> None:
    a = _cardapio(
        (
            "Lanches",
            [
                _item(
                    "X-Tudo",
                    descricao_original="Pão e carne",
                    alergenicos_provaveis=["gluten"],
                    adicionais=[OpcaoPreco(nome="Bacon", preco=Decimal("4.00"))],
                )
            ],
        )
    )
    b = _cardapio(
        (
            "Lanches",
            [
                _item(
                    "X-Tudo",
                    descricao_original="Pão, carne e queijo",
                    alergenicos_provaveis=["gluten", "lactose"],
                    adicionais=[OpcaoPreco(nome="Ovo", preco=Decimal("2.00"))],
                )
            ],
        )
    )
    item = unir_cardapios([a, b]).categorias[0].itens[0]
    assert item.descricao_original == "Pão, carne e queijo"
    assert [a.value for a in item.alergenicos_provaveis] == ["gluten", "lactose"]
    assert [a.nome for a in item.adicionais] == ["Bacon", "Ovo"]


def test_nome_parecido_com_mesmo_preco_e_o_mesmo_item() -> None:
    a = _cardapio(("Pizzas", [_item("Pizza de Mussarela", "40.00")]))
    b = _cardapio(("Pizzas", [_item("Pizza de Muçarela", "40.00")]))
    assert len(_nomes(unir_cardapios([a, b]))) == 1


def test_nome_parecido_com_preco_diferente_nao_une() -> None:
    a = _cardapio(("Pizzas", [_item("Pizza de Mussarela", "40.00")]))
    b = _cardapio(("Pizzas", [_item("Pizza de Muçarela", "45.00")]))
    assert len(_nomes(unir_cardapios([a, b]))) == 2


def test_numeros_diferentes_no_nome_nunca_unem() -> None:
    a = _cardapio(("Combos", [_item("Combo 2 Pessoas", None)]))
    b = _cardapio(("Combos", [_item("Combo 3 Pessoas", None)]))
    assert len(_nomes(unir_cardapios([a, b]))) == 2


def test_info_do_restaurante_usa_o_primeiro_valor_de_cada_campo() -> None:
    a = ExtracaoCardapio(
        info_restaurante=InfoRestaurante(nome="Casa", telefone=None, horario=None), categorias=[]
    )
    b = ExtracaoCardapio(
        info_restaurante=InfoRestaurante(nome="Outro", telefone="1234", horario=None),
        categorias=[],
    )
    info = unir_cardapios([a, b]).info_restaurante
    assert (info.nome, info.telefone, info.horario) == ("Casa", "1234", None)


def _pizza(
    nome: str, descricao: str = "Presunto, ovo, cebola e azeitona", **extras: Any
) -> ItemExtraido:
    variacoes = [OpcaoPreco(nome="Meia", preco=Decimal("32.00"))]
    return _item(nome, None, descricao_original=descricao, variacoes=variacoes, **extras)


def test_linha_de_ingredientes_lida_como_nome_nao_vira_item() -> None:
    a = _cardapio(("Pizzas", [_pizza("Portuguesa")]))
    b = _cardapio(("Pizzas", [_pizza("Presunto")]))
    assert _nomes(unir_cardapios([a, b])) == [("Pizzas", "Portuguesa")]


def test_fragmento_na_primeira_foto_da_lugar_ao_nome_verdadeiro() -> None:
    a = _cardapio(("Pizzas", [_pizza("Presunto")]))
    b = _cardapio(("Pizzas", [_pizza("Portuguesa")]))
    assert _nomes(unir_cardapios([a, b])) == [("Pizzas", "Portuguesa")]


def test_mesma_descricao_sem_fragmento_continua_separado() -> None:
    a = _cardapio(("Pizzas", [_pizza("Portuguesa")]))
    b = _cardapio(("Pizzas", [_pizza("Moda da casa")]))
    assert len(_nomes(unir_cardapios([a, b]))) == 2


def test_fragmento_com_preco_diferente_continua_separado() -> None:
    a = _cardapio(("Pizzas", [_pizza("Portuguesa")]))
    fragmento = _pizza("Presunto").model_copy(
        update={"variacoes": [OpcaoPreco(nome="Meia", preco=Decimal("35.00"))]}
    )
    b = _cardapio(("Pizzas", [fragmento]))
    assert len(_nomes(unir_cardapios([a, b]))) == 2
