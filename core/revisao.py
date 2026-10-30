"""Regras que marcam itens para revisão humana."""

from collections.abc import Iterable

from core.schema import ExtracaoCardapio, ItemExtraido, ItemParaRevisao, MotivoRevisao

ROTULOS_MOTIVO = {
    MotivoRevisao.CONFIANCA_BAIXA: "leitura incerta",
    MotivoRevisao.PRECO_AUSENTE: "sem preço",
    MotivoRevisao.PRECO_VARIACAO_AUSENTE: "variação sem preço",
    MotivoRevisao.PRECO_ADICIONAL_AUSENTE: "adicional sem preço",
}


def rotular_motivos(motivos: Iterable[MotivoRevisao]) -> str:
    """Motivos em texto para o dono do restaurante (vazio se não houver nenhum)."""
    return ", ".join(ROTULOS_MOTIVO[motivo] for motivo in motivos)


def motivos_do_item(item: ItemExtraido, limiar_confianca: float) -> list[MotivoRevisao]:
    """Lista os motivos pelos quais um item precisa de revisão (vazia se nenhum)."""
    motivos: list[MotivoRevisao] = []
    if item.confianca < limiar_confianca:
        motivos.append(MotivoRevisao.CONFIANCA_BAIXA)
    if item.preco is None and not any(v.preco is not None for v in item.variacoes):
        motivos.append(MotivoRevisao.PRECO_AUSENTE)
    if any(v.preco is None for v in item.variacoes):
        motivos.append(MotivoRevisao.PRECO_VARIACAO_AUSENTE)
    if any(a.preco is None for a in item.adicionais):
        motivos.append(MotivoRevisao.PRECO_ADICIONAL_AUSENTE)
    return motivos


def itens_para_revisao(
    cardapio: ExtracaoCardapio, limiar_confianca: float
) -> list[ItemParaRevisao]:
    """Percorre o cardápio e devolve os itens que precisam de revisão."""
    pendentes: list[ItemParaRevisao] = []
    for categoria in cardapio.categorias:
        for indice, item in enumerate(categoria.itens):
            motivos = motivos_do_item(item, limiar_confianca)
            if motivos:
                pendentes.append(
                    ItemParaRevisao(
                        categoria=categoria.nome,
                        indice_item=indice,
                        nome=item.nome,
                        motivos=motivos,
                    )
                )
    return pendentes
