"""Página única: upload, tabela editável com itens a revisar e exportação."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from core.arquivos import preparar_arquivo
from core.config import Config
from core.edicao import (
    ROTULOS_ALERGENICOS,
    CardapioEditado,
    Linha,
    aplicar_edicao,
    para_linhas,
)
from core.export import exportar_csv, exportar_json
from core.extract import ERROS_EXTRACAO, extrair_de_midias
from core.providers import criar_provedor
from core.providers.base import Midia
from core.revisao import rotular_motivos
from core.schema import Alergenico, InfoRestaurante, ResultadoExtracao

CHAVE_EXTRACAO = "extracao"
CHAVE_VERSAO = "versao_extracao"
TIPOS_ACEITOS = ["jpg", "jpeg", "png", "pdf"]
COR_DESTAQUE = "background-color: rgba(255, 193, 7, 0.3)"
ALTURA_LINHA = 36  # px; as duas linhas extras são o cabeçalho e a de adicionar item
ALTURA_MAXIMA_TABELA = 800
AJUDA_OPCOES = "Formato: nome: preço; nome: preço. Use ? quando o preço for desconhecido."

COLUNAS_TABELA: dict[str, Any] = {
    "alerta": st.column_config.TextColumn(
        "Alerta da IA", disabled=True, pinned=True, width="medium"
    ),
    "conferido": st.column_config.CheckboxColumn(
        "Conferido", default=False, help="Marque depois de comparar o item com o cardápio."
    ),
    "categoria": st.column_config.TextColumn("Categoria", required=True),
    "nome": st.column_config.TextColumn("Item", required=True, width="medium"),
    "preco": st.column_config.NumberColumn(
        "Preço (R$)",
        min_value=0.01,
        step=0.01,
        format="%.2f",
        help="Deixe vazio se não souber. Nunca use 0.",
    ),
    "variacoes": st.column_config.TextColumn("Variações", width="medium", help=AJUDA_OPCOES),
    "adicionais": st.column_config.TextColumn("Adicionais", width="medium", help=AJUDA_OPCOES),
    "descricao": st.column_config.TextColumn("Descrição", width="large"),
    "alergenicos": st.column_config.MultiselectColumn(
        "Alergênicos prováveis",
        options=list(ROTULOS_ALERGENICOS),
        format_func=lambda valor: ROTULOS_ALERGENICOS[Alergenico(valor)],
        help="Sugestão da IA pelos ingredientes citados, não é uma certeza.",
    ),
    "confianca": st.column_config.NumberColumn("Confiança", disabled=True, format="percent"),
    "observacao": st.column_config.TextColumn("Observação da IA", disabled=True, width="large"),
}


@dataclass(eq=False)
class Extracao:
    """O que fica guardado na sessão depois de uma extração bem-sucedida."""

    versao: int
    nome_arquivo: str
    midia: Midia
    resultado: ResultadoExtracao
    tabela: pd.DataFrame  # nunca alterada: as edições vivem no estado do st.data_editor


def main() -> None:
    st.set_page_config(page_title="Cardápio Instantâneo", page_icon="🍽️", layout="wide")
    st.title("Cardápio Instantâneo")
    st.write("Envie a foto ou o PDF do cardápio e revise o resultado antes de exportar.")
    config = Config()
    _secao_upload(config)
    extracao: Extracao | None = st.session_state.get(CHAVE_EXTRACAO)
    if extracao is not None:
        _secao_revisao(extracao, config)


def _secao_upload(config: Config) -> None:
    arquivo = st.file_uploader("Foto ou PDF do cardápio", type=TIPOS_ACEITOS)
    st.caption("O arquivo é enviado ao provedor de IA configurado para fazer a leitura.")
    if st.button("Extrair cardápio", type="primary", disabled=arquivo is None) and arquivo:
        _extrair(arquivo.getvalue(), arquivo.name, config)


def _extrair(dados: bytes, nome: str, config: Config) -> None:
    with st.spinner("Lendo o cardápio..."):
        try:
            midia = preparar_arquivo(dados, nome, config.max_lado_imagem)
            resultado = extrair_de_midias([midia], criar_provedor(config), config, origem=nome)
        except ERROS_EXTRACAO as erro:
            st.error(f"Não foi possível ler o cardápio. {erro}")
            return
    versao = st.session_state.get(CHAVE_VERSAO, 0) + 1
    st.session_state[CHAVE_VERSAO] = versao
    tabela = _criar_tabela(para_linhas(resultado.cardapio, config.limiar_confianca))
    st.session_state[CHAVE_EXTRACAO] = Extracao(versao, nome, midia, resultado, tabela)


def _criar_tabela(linhas: list[Linha]) -> pd.DataFrame:
    tabela = pd.DataFrame(linhas, columns=list(COLUNAS_TABELA))
    tabela["alerta"] = tabela["alerta"].map(lambda texto: f"⚠️ {texto}" if texto else "")
    return tabela


def _secao_revisao(extracao: Extracao, config: Config) -> None:
    st.divider()
    st.subheader("Revise o cardápio")
    _mostrar_metricas(extracao.resultado)
    if extracao.resultado.cardapio.total_itens() == 0:
        st.warning("Nenhum item foi encontrado nesse arquivo. Você pode adicionar itens à mão.")
    coluna_arquivo, coluna_tabela = st.columns([1, 2], gap="medium")
    with coluna_arquivo:
        _mostrar_arquivo(extracao)
    with coluna_tabela:
        info = _editar_info(extracao)
        situacao = st.container()
        edicao = aplicar_edicao(
            _editar_tabela(extracao),
            info,
            _categorias_inferidas(extracao.resultado),
            config.limiar_confianca,
        )
        with situacao:
            _mostrar_situacao(edicao)
        _secao_exportacao(edicao, extracao.nome_arquivo)


def _mostrar_metricas(resultado: ResultadoExtracao) -> None:
    metricas = resultado.metricas
    custo = (
        f"US$ {metricas.custo_estimado_usd:.4f}"
        if metricas.custo_estimado_usd is not None
        else "custo não cadastrado"
    )
    st.caption(f"{metricas.modelo} · {metricas.tempo_s:.1f} s · {custo}")


def _mostrar_arquivo(extracao: Extracao) -> None:
    if extracao.midia.mime == "application/pdf":
        st.info(f"PDF enviado: {extracao.nome_arquivo}")
    else:
        st.image(extracao.midia.dados, caption=extracao.nome_arquivo, width="stretch")


def _editar_info(extracao: Extracao) -> InfoRestaurante:
    atual = extracao.resultado.cardapio.info_restaurante
    prefixo = f"info_{extracao.versao}"
    coluna_nome, coluna_telefone, coluna_horario = st.columns(3)
    nome = coluna_nome.text_input("Restaurante", atual.nome or "", key=f"{prefixo}_nome")
    telefone = coluna_telefone.text_input(
        "Telefone", atual.telefone or "", key=f"{prefixo}_telefone"
    )
    horario = coluna_horario.text_input("Horário", atual.horario or "", key=f"{prefixo}_horario")
    return InfoRestaurante(nome=nome or None, telefone=telefone or None, horario=horario or None)


def _editar_tabela(extracao: Extracao) -> list[Linha]:
    editada = st.data_editor(
        extracao.tabela.style.apply(_destacar_linha, axis=1),
        key=f"tabela_{extracao.versao}",
        column_config=COLUNAS_TABELA,
        column_order=list(COLUNAS_TABELA),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        height=min(ALTURA_LINHA * (len(extracao.tabela) + 2), ALTURA_MAXIMA_TABELA),
        placeholder="—",
    )
    return _linhas_da_tabela(editada)


def _destacar_linha(linha: pd.Series) -> list[str]:
    """O Streamlit só aplica cor nas colunas somente leitura: alerta, confiança e observação."""
    return [COR_DESTAQUE if linha["alerta"] else ""] * len(linha)


def _linhas_da_tabela(tabela: pd.DataFrame) -> list[Linha]:
    """Registros da tabela, com células vazias sempre como None."""
    registros: list[Linha] = tabela.astype(object).where(tabela.notna(), None).to_dict("records")
    return registros


def _categorias_inferidas(resultado: ResultadoExtracao) -> list[str]:
    return [c.nome for c in resultado.cardapio.categorias if c.categoria_inferida]


def _mostrar_situacao(edicao: CardapioEditado) -> None:
    if edicao.erros:
        erros = "\n".join(
            f"- Linha {e.linha} ({e.item or 'sem nome'}): {e.mensagem}" for e in edicao.erros
        )
        st.error(f"Corrija antes de exportar:\n\n{erros}")
    elif edicao.pendencias:
        itens = "\n".join(
            f"- **{p.nome}** ({p.categoria}): {rotular_motivos(p.motivos)}"
            for p in edicao.pendencias
        )
        st.warning(
            f"**{len(edicao.pendencias)} item(ns) para revisar.** Compare com o cardápio, "
            f"corrija o que for preciso e marque **Conferido**.\n\n{itens}"
        )
    else:
        st.success("Nenhum item pendente de revisão.")


def _secao_exportacao(edicao: CardapioEditado, nome_arquivo: str) -> None:
    cardapio = edicao.cardapio
    pronto = cardapio is not None
    json_saida = exportar_json(cardapio, edicao.pendencias) if cardapio else b""
    csv_saida = exportar_csv(cardapio, edicao.pendencias) if cardapio else b""
    base = Path(nome_arquivo).stem
    coluna_json, coluna_csv = st.columns(2)
    coluna_json.download_button(
        "Baixar JSON",
        json_saida,
        file_name=f"{base}.json",
        mime="application/json",
        disabled=not pronto,
        on_click="ignore",
        width="stretch",
    )
    coluna_csv.download_button(
        "Baixar CSV",
        csv_saida,
        file_name=f"{base}.csv",
        mime="text/csv",
        disabled=not pronto,
        on_click="ignore",
        width="stretch",
    )
    if pronto and edicao.pendencias:
        st.caption("Você pode exportar agora: os itens pendentes ficam marcados no arquivo.")
