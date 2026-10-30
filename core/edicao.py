"""Conversão entre o cardápio e as linhas da tabela editável (sem depender da interface)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from core.revisao import motivos_do_item, rotular_motivos
from core.schema import (
    Alergenico,
    CategoriaExtraida,
    ExtracaoCardapio,
    InfoRestaurante,
    ItemExtraido,
    ItemParaRevisao,
    OpcaoPreco,
)

Linha = dict[str, Any]

PRECO_DESCONHECIDO = "?"
CONFIANCA_ITEM_MANUAL = 1.0
CAMPOS_DE_CONTEUDO = ("categoria", "nome", "preco", "variacoes", "adicionais", "descricao")
ROTULOS_ALERGENICOS = {
    Alergenico.GLUTEN: "glúten",
    Alergenico.LACTOSE: "lactose",
    Alergenico.OVO: "ovo",
    Alergenico.AMENDOIM: "amendoim",
    Alergenico.CASTANHAS: "castanhas",
    Alergenico.FRUTOS_DO_MAR: "frutos do mar",
    Alergenico.SOJA: "soja",
}


@dataclass(frozen=True)
class ErroLinha:
    linha: int  # começa em 1, de cima para baixo
    item: str  # a tabela não mostra números de linha: o nome ajuda a achar o erro
    mensagem: str


@dataclass(frozen=True)
class DescricaoEscolhida:
    """Sugestão disponível para um item e a escolha do dono: a original nunca é apagada."""

    sugerida: str
    usar: bool


Descricoes = dict[tuple[str, int], DescricaoEscolhida]  # (categoria, índice do item)


@dataclass(frozen=True)
class CardapioEditado:
    """Resultado de ler a tabela: ou há cardápio, ou há erros a corrigir."""

    cardapio: ExtracaoCardapio | None
    pendencias: list[ItemParaRevisao]
    erros: list[ErroLinha]
    descricoes: Descricoes = field(default_factory=dict)


def formatar_preco(preco: Decimal) -> str:
    """32.9 vira '32,90'."""
    return f"{preco:.2f}".replace(".", ",")


def formatar_opcoes(opcoes: Iterable[OpcaoPreco]) -> str:
    """Variações ou adicionais em texto editável: 'P: 18,00; G: ?'."""
    return "; ".join(
        f"{o.nome}: {formatar_preco(o.preco) if o.preco is not None else PRECO_DESCONHECIDO}"
        for o in opcoes
    )


def interpretar_opcoes(texto: str) -> list[OpcaoPreco]:
    """Lê o texto de ``formatar_opcoes``; ValueError explica o que está errado."""
    opcoes: list[OpcaoPreco] = []
    for parte in (p.strip() for p in texto.split(";")):
        if not parte:
            continue
        nome, separador, preco = parte.rpartition(":")
        if not separador or not nome.strip():
            raise ValueError(f"'{parte}' não está no formato 'nome: preço'")
        opcoes.append(OpcaoPreco(nome=nome.strip(), preco=_preco_de_texto(preco)))
    return opcoes


def para_linhas(cardapio: ExtracaoCardapio, limiar_confianca: float) -> list[Linha]:
    """Uma linha por item, na ordem do cardápio."""
    return [
        _linha_do_item(categoria.nome, item, limiar_confianca)
        for categoria in cardapio.categorias
        for item in categoria.itens
    ]


def aplicar_edicao(
    linhas: Sequence[Linha],
    info: InfoRestaurante,
    categorias_inferidas: Iterable[str],
    limiar_confianca: float,
) -> CardapioEditado:
    """Reconstrói o cardápio a partir da tabela e recalcula o que ainda precisa de revisão."""
    por_categoria: dict[str, list[ItemExtraido]] = {}
    pendencias: list[ItemParaRevisao] = []
    erros: list[ErroLinha] = []
    descricoes: Descricoes = {}
    for numero, linha in enumerate(linhas, start=1):
        if _linha_vazia(linha):
            continue
        try:
            categoria, item = _ler_linha(linha)
        except ValidationError as erro:
            detalhes = "; ".join(d["msg"] for d in erro.errors(include_url=False))
            erros.append(ErroLinha(numero, _texto(linha.get("nome")), detalhes))
        except ValueError as erro:
            erros.append(ErroLinha(numero, _texto(linha.get("nome")), str(erro)))
        else:
            itens = por_categoria.setdefault(categoria, [])
            motivos = motivos_do_item(item, limiar_confianca)
            if motivos and not linha.get("conferido"):
                pendencias.append(
                    ItemParaRevisao(
                        categoria=categoria, indice_item=len(itens), nome=item.nome, motivos=motivos
                    )
                )
            sugerida = _texto(linha.get("descricao_sugerida"))
            if sugerida:
                descricoes[(categoria, len(itens))] = DescricaoEscolhida(
                    sugerida, bool(linha.get("usar_sugestao"))
                )
            itens.append(item)
    if erros:
        return CardapioEditado(None, [], erros)
    inferidas = set(categorias_inferidas)
    cardapio = ExtracaoCardapio(
        info_restaurante=info,
        categorias=[
            CategoriaExtraida(nome=nome, categoria_inferida=nome in inferidas, itens=itens)
            for nome, itens in por_categoria.items()
        ],
    )
    return CardapioEditado(cardapio, pendencias, [], descricoes)


def _linha_do_item(categoria: str, item: ItemExtraido, limiar_confianca: float) -> Linha:
    return {
        "alerta": rotular_motivos(motivos_do_item(item, limiar_confianca)),
        "conferido": False,
        "categoria": categoria,
        "nome": item.nome,
        "preco": float(item.preco) if item.preco is not None else None,
        "variacoes": formatar_opcoes(item.variacoes),
        "adicionais": formatar_opcoes(item.adicionais),
        "descricao": item.descricao_original or "",
        "descricao_sugerida": "",
        "usar_sugestao": False,
        "alergenicos": [alergenico.value for alergenico in item.alergenicos_provaveis],
        "confianca": item.confianca,
        "observacao": item.observacao or "",
    }


def _ler_linha(linha: Linha) -> tuple[str, ItemExtraido]:
    categoria = _texto(linha.get("categoria"))
    if not categoria:
        raise ValueError("informe a categoria")
    nome = _texto(linha.get("nome"))
    if not nome:
        raise ValueError("informe o nome do item")
    confianca = linha.get("confianca")
    item = ItemExtraido(
        nome=nome,
        descricao_original=_texto(linha.get("descricao")) or None,
        preco=_preco_de_numero(linha.get("preco")),
        variacoes=interpretar_opcoes(_texto(linha.get("variacoes"))),
        adicionais=interpretar_opcoes(_texto(linha.get("adicionais"))),
        alergenicos_provaveis=[Alergenico(a) for a in _lista(linha.get("alergenicos"))],
        confianca=CONFIANCA_ITEM_MANUAL if _ausente(confianca) else float(confianca),  # type: ignore[arg-type]
        observacao=_texto(linha.get("observacao")) or None,
    )
    return categoria, item


def _preco_de_texto(texto: str) -> Decimal | None:
    limpo = texto.replace("R$", "").strip()
    if limpo in ("", PRECO_DESCONHECIDO):
        return None
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return _validar_preco(Decimal(limpo))
    except InvalidOperation as erro:
        raise ValueError(f"'{texto.strip()}' não é um preço válido") from erro


def _preco_de_numero(valor: Any) -> Decimal | None:
    if _ausente(valor):
        return None
    return _validar_preco(Decimal(str(valor)))


def _validar_preco(preco: Decimal) -> Decimal:
    if not preco.is_finite() or preco <= 0:
        raise ValueError("o preço deve ser maior que zero (deixe vazio se não souber)")
    expoente = preco.as_tuple().exponent
    if isinstance(expoente, int) and expoente < -2:
        raise ValueError(f"o preço {preco} tem mais de 2 casas decimais")
    return preco


def _ausente(valor: Any) -> bool:
    """None ou NaN: é como a tabela representa uma célula vazia."""
    return valor is None or valor != valor


def _texto(valor: Any) -> str:
    return "" if _ausente(valor) else str(valor).strip()


def _lista(valor: Any) -> list[str]:
    if isinstance(valor, str):
        return [valor] if valor else []
    if valor is None or (isinstance(valor, float) and valor != valor):
        return []
    return list(valor)


def _linha_vazia(linha: Linha) -> bool:
    return all(_texto(linha.get(campo)) == "" for campo in CAMPOS_DE_CONTEUDO)
