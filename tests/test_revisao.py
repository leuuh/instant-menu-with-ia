from core.revisao import itens_para_revisao, motivos_do_item
from core.schema import ExtracaoCardapio, MotivoRevisao


def _cardapio(json_valido: str) -> ExtracaoCardapio:
    return ExtracaoCardapio.model_validate_json(json_valido)


def test_item_confiavel_com_preco_nao_vai_para_revisao(json_valido: str) -> None:
    x_burguer = _cardapio(json_valido).categorias[0].itens[0]
    assert motivos_do_item(x_burguer, 0.7) == []


def test_preco_ausente_e_confianca_baixa(json_valido: str) -> None:
    x_salada = _cardapio(json_valido).categorias[0].itens[1]
    assert motivos_do_item(x_salada, 0.7) == [
        MotivoRevisao.CONFIANCA_BAIXA,
        MotivoRevisao.PRECO_AUSENTE,
    ]


def test_item_com_variacoes_precificadas_nao_e_preco_ausente(json_valido: str) -> None:
    calabresa = _cardapio(json_valido).categorias[1].itens[0]
    assert calabresa.preco is None
    assert motivos_do_item(calabresa, 0.7) == [MotivoRevisao.PRECO_ADICIONAL_AUSENTE]


def test_variacao_sem_preco(json_valido: str) -> None:
    suco = _cardapio(json_valido).categorias[2].itens[0]
    assert motivos_do_item(suco, 0.7) == [MotivoRevisao.PRECO_VARIACAO_AUSENTE]


def test_limiar_configuravel(json_valido: str) -> None:
    suco = _cardapio(json_valido).categorias[2].itens[0]  # confianca 0.8
    assert MotivoRevisao.CONFIANCA_BAIXA in motivos_do_item(suco, 0.85)


def test_itens_para_revisao_aponta_categoria_e_indice(json_valido: str) -> None:
    pendentes = itens_para_revisao(_cardapio(json_valido), 0.7)
    assert [(p.categoria, p.indice_item, p.nome) for p in pendentes] == [
        ("Lanches", 1, "X-Salada"),
        ("Pizzas", 0, "Calabresa"),
        ("Bebidas", 0, "Suco de laranja"),
    ]
