"""Exportação do cardápio em JSON e CSV."""

import csv
import io
import json
from collections.abc import Iterator, Sequence
from decimal import Decimal

from core.edicao import ROTULOS_ALERGENICOS, formatar_opcoes, formatar_preco
from core.revisao import rotular_motivos
from core.schema import ExtracaoCardapio, ItemExtraido, ItemParaRevisao

COLUNAS_CSV = (
    "categoria",
    "item",
    "descricao",
    "opcao",
    "preco",
    "adicionais",
    "alergenicos_provaveis",
    "confianca",
    "pendente_revisao",
    "motivos_revisao",
    "observacao",
)
INICIOS_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def exportar_json(cardapio: ExtracaoCardapio, pendencias: Sequence[ItemParaRevisao]) -> bytes:
    """Mesmo formato do contrato do LLM, mais a lista do que ainda precisa de revisão."""
    dados = {
        **cardapio.model_dump(mode="json"),
        "pendencias_revisao": [p.model_dump(mode="json") for p in pendencias],
    }
    return json.dumps(dados, ensure_ascii=False, indent=2).encode("utf-8")


def exportar_csv(cardapio: ExtracaoCardapio, pendencias: Sequence[ItemParaRevisao]) -> bytes:
    """Uma linha por preço, pronto para o Excel em português: ';', vírgula decimal e BOM UTF-8."""
    motivos = {(p.categoria, p.indice_item): rotular_motivos(p.motivos) for p in pendencias}
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow(COLUNAS_CSV)
    for categoria in cardapio.categorias:
        for indice, item in enumerate(categoria.itens):
            motivo = motivos.get((categoria.nome, indice), "")
            for opcao, preco in _precos_do_item(item):
                escritor.writerow(_linha_csv(categoria.nome, item, opcao, preco, motivo))
    return buffer.getvalue().encode("utf-8-sig")


def _precos_do_item(item: ItemExtraido) -> Iterator[tuple[str, Decimal | None]]:
    """Preço do item (vazio se desconhecido, nunca 0) e o de cada variação."""
    if item.preco is not None or not item.variacoes:
        yield "", item.preco
    for variacao in item.variacoes:
        yield variacao.nome, variacao.preco


def _linha_csv(
    categoria: str, item: ItemExtraido, opcao: str, preco: Decimal | None, motivo: str
) -> list[str]:
    return [
        _celula_segura(categoria),
        _celula_segura(item.nome),
        _celula_segura(item.descricao_original or ""),
        _celula_segura(opcao),
        formatar_preco(preco) if preco is not None else "",
        _celula_segura(formatar_opcoes(item.adicionais)),
        ", ".join(ROTULOS_ALERGENICOS[a] for a in item.alergenicos_provaveis),
        f"{item.confianca:.2f}".replace(".", ","),
        "sim" if motivo else "não",
        motivo,
        _celula_segura(item.observacao or ""),
    ]


def _celula_segura(texto: str) -> str:
    """Impede o Excel de executar texto como fórmula (ex.: '+ Bacon' ou '=...')."""
    return f"'{texto}" if texto.startswith(INICIOS_DE_FORMULA) else texto
