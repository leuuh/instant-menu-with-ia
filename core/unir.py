"""União dos cardápios lidos de várias fotos, removendo itens repetidos.

A regra é conservadora: um item repetido que escapa fica visível e o dono apaga; dois itens
diferentes unidos por engano fariam um preço sumir. Se as fotos discordam sobre um preço, ele
vira null e os valores vão para a observação: o sistema nunca escolhe um dos dois sozinho.
"""

import difflib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.edicao import formatar_preco
from core.schema import (
    CategoriaExtraida,
    ExtracaoCardapio,
    InfoRestaurante,
    ItemExtraido,
    OpcaoPreco,
)

SEMELHANCA_MINIMA = 0.9


@dataclass
class _Categoria:
    nome: str
    inferida: bool
    itens: list[ItemExtraido]


def unir_cardapios(cardapios: Sequence[ExtracaoCardapio]) -> ExtracaoCardapio:
    """Une os cardápios na ordem recebida. Um cardápio só é devolvido sem alteração."""
    if len(cardapios) == 1:
        return cardapios[0]
    categorias: dict[str, _Categoria] = {}
    for cardapio in cardapios:
        for categoria in cardapio.categorias:
            _acrescentar_categoria(categorias, categoria)
    return ExtracaoCardapio(
        info_restaurante=_unir_info([c.info_restaurante for c in cardapios]),
        categorias=[
            CategoriaExtraida(nome=c.nome, categoria_inferida=c.inferida, itens=c.itens)
            for c in categorias.values()
        ],
    )


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos nem pontuação: 'X-Búrguer!' e 'x burguer' ficam iguais."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).split())


def _acrescentar_categoria(categorias: dict[str, _Categoria], nova: CategoriaExtraida) -> None:
    chave = normalizar(nova.nome)
    atual = categorias.get(chave)
    if atual is None:
        atual = categorias[chave] = _Categoria(nova.nome, nova.categoria_inferida, [])
    elif atual.inferida and not nova.categoria_inferida:
        atual.nome, atual.inferida = nova.nome, False
    for item in nova.itens:
        _acrescentar_item(categorias, atual, item, nova.categoria_inferida)


def _acrescentar_item(
    categorias: dict[str, _Categoria],
    destino: _Categoria,
    item: ItemExtraido,
    item_inferido: bool,
) -> None:
    alvo = _achar_repetido(categorias, destino, item, item_inferido)
    if alvo is None:
        destino.itens.append(item)
    else:
        categoria, indice = alvo
        categoria.itens[indice] = _mesclar(categoria.itens[indice], item)


def _achar_repetido(
    categorias: dict[str, _Categoria],
    destino: _Categoria,
    item: ItemExtraido,
    item_inferido: bool,
) -> tuple[_Categoria, int] | None:
    """Na mesma categoria, ou em outra quando uma delas foi só deduzida pelo modelo."""
    for indice, existente in enumerate(destino.itens):
        if _mesmo_item(existente, item):
            return destino, indice
    for categoria in categorias.values():
        if categoria is destino or not (item_inferido or categoria.inferida):
            continue
        for indice, existente in enumerate(categoria.itens):
            if normalizar(existente.nome) == normalizar(item.nome) and _precos_compativeis(
                existente, item
            ):
                return categoria, indice
    return None


def _mesmo_item(a: ItemExtraido, b: ItemExtraido) -> bool:
    nome_a, nome_b = normalizar(a.nome), normalizar(b.nome)
    if nome_a == nome_b or _fragmento_do_mesmo_item(a, b):
        return True
    # "Combo 2 pessoas" e "Combo 3 pessoas" são parecidos, mas são itens diferentes.
    if re.findall(r"\d+", nome_a) != re.findall(r"\d+", nome_b):
        return False
    parecidos = difflib.SequenceMatcher(None, nome_a, nome_b).ratio() >= SEMELHANCA_MINIMA
    return parecidos and _precos_compativeis(a, b)


def _fragmento_do_mesmo_item(a: ItemExtraido, b: ItemExtraido) -> bool:
    """Foto cortada no meio de um item: a linha de ingredientes pode virar o nome."""
    return (
        (_nome_e_fragmento(a) or _nome_e_fragmento(b))
        and normalizar(a.descricao_original or "") == normalizar(b.descricao_original or "")
        and a.preco == b.preco
        and _precos_das_opcoes(a) == _precos_das_opcoes(b)
    )


def _nome_e_fragmento(item: ItemExtraido) -> bool:
    descricao = normalizar(item.descricao_original or "")
    return bool(descricao) and descricao.startswith(normalizar(item.nome))


def _precos_das_opcoes(item: ItemExtraido) -> set[tuple[str, Decimal | None]]:
    return {(normalizar(v.nome), v.preco) for v in item.variacoes}


def _precos_compativeis(a: ItemExtraido, b: ItemExtraido) -> bool:
    return a.preco is None or b.preco is None or a.preco == b.preco


def _mesclar(a: ItemExtraido, b: ItemExtraido) -> ItemExtraido:
    preco, conflito = _unir_preco(a.preco, b.preco)
    variacoes, conflitos_variacoes = _unir_opcoes(a.variacoes, b.variacoes)
    adicionais, conflitos_adicionais = _unir_opcoes(a.adicionais, b.adicionais)
    conflitos = [*conflitos_variacoes, *conflitos_adicionais]
    if conflito:
        conflitos.insert(0, f"Preço do item: {conflito}")
    return ItemExtraido(
        nome=b.nome if _nome_e_fragmento(a) and not _nome_e_fragmento(b) else a.nome,
        descricao_original=_mais_longo(a.descricao_original, b.descricao_original),
        preco=preco,
        variacoes=variacoes,
        adicionais=adicionais,
        alergenicos_provaveis=list(
            dict.fromkeys([*a.alergenicos_provaveis, *b.alergenicos_provaveis])
        ),
        confianca=_unir_confianca(a, b, bool(conflitos)),
        observacao=_unir_observacoes(a.observacao, b.observacao, conflitos),
    )


def _unir_preco(a: Decimal | None, b: Decimal | None) -> tuple[Decimal | None, str | None]:
    """Devolve o preço e, se as leituras discordam, null com a descrição do conflito."""
    if a is not None and b is not None and a != b:
        return None, f"as fotos mostram {formatar_preco(a)} e {formatar_preco(b)}"
    return (a if a is not None else b), None


def _unir_opcoes(
    a: Sequence[OpcaoPreco], b: Sequence[OpcaoPreco]
) -> tuple[list[OpcaoPreco], list[str]]:
    """Une variações ou adicionais pelo nome, mantendo a ordem da primeira foto."""
    unidas = {normalizar(opcao.nome): opcao for opcao in a}
    conflitos: list[str] = []
    for opcao in b:
        chave = normalizar(opcao.nome)
        existente = unidas.get(chave)
        if existente is None:
            unidas[chave] = opcao
            continue
        preco, conflito = _unir_preco(existente.preco, opcao.preco)
        unidas[chave] = OpcaoPreco(nome=existente.nome, preco=preco)
        if conflito:
            conflitos.append(f"{existente.nome}: {conflito}")
    return list(unidas.values()), conflitos


def _unir_confianca(a: ItemExtraido, b: ItemExtraido, tem_conflito: bool) -> float:
    if tem_conflito:
        return min(a.confianca, b.confianca)
    if a.preco is not None and b.preco is None:
        return a.confianca  # vale a confiança da leitura que trouxe o preço
    if b.preco is not None and a.preco is None:
        return b.confianca
    return max(a.confianca, b.confianca)


def _unir_observacoes(a: str | None, b: str | None, conflitos: list[str]) -> str | None:
    partes = [parte for parte in (a, b, *conflitos) if parte]
    return " | ".join(dict.fromkeys(partes)) or None


def _mais_longo(a: str | None, b: str | None) -> str | None:
    return max((a or "", b or ""), key=len) or None


def _unir_info(infos: Sequence[InfoRestaurante]) -> InfoRestaurante:
    return InfoRestaurante(
        nome=next((i.nome for i in infos if i.nome), None),
        telefone=next((i.telefone for i in infos if i.telefone), None),
        horario=next((i.horario for i in infos if i.horario), None),
    )
