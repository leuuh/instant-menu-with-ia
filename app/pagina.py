"""Página única: upload, painel, tabela editável, descrições sugeridas e exportação."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.arquivos import Entrada, preparar_arquivos
from core.config import Config
from core.edicao import (
    ROTULOS_ALERGENICOS,
    CardapioEditado,
    Linha,
    aplicar_edicao,
    para_linhas,
)
from core.enrich import ItemParaDescrever, ResultadoDescricoes, gerar_descricoes
from core.export import exportar_csv, exportar_json
from core.extract import ERROS_EXTRACAO, extrair_entradas
from core.precos import VERIFICADO_EM
from core.providers import criar_provedor
from core.revisao import rotular_motivos
from core.schema import Alergenico, InfoRestaurante, MetricasLLM, ResultadoExtracao

CHAVE_EXTRACAO = "extracao"
CHAVE_VERSAO = "versao_extracao"
CHAVE_MENSAGEM = "mensagem_descricoes"
TIPOS_ACEITOS = ["jpg", "jpeg", "png", "pdf"]
COR_DESTAQUE = "background-color: rgba(255, 193, 7, 0.3)"
ALTURA_LINHA = 36  # px; as duas linhas extras são o cabeçalho e a de adicionar item
ALTURA_MAXIMA_TABELA = 800
AJUDA_OPCOES = "Formato: nome: preço; nome: preço. Use ? quando o preço for desconhecido."
BASE_ARQUIVO_VARIOS = "cardapio"

COLUNAS_TEXTO = ("categoria", "nome", "variacoes", "adicionais", "descricao", "observacao")
COLUNAS_SUGESTAO = ("descricao_sugerida", "usar_sugestao")

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
    "descricao": st.column_config.TextColumn("Descrição original", width="large"),
    "descricao_sugerida": st.column_config.TextColumn(
        "Descrição sugerida",
        width="large",
        help="Sugestão da IA. Confira se não mudou nada do prato; você pode editar o texto.",
    ),
    "usar_sugestao": st.column_config.CheckboxColumn(
        "Usar sugestão", default=False, help="Marcado: a sugestão vai para o arquivo exportado."
    ),
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
    entradas: list[Entrada]
    resultado: ResultadoExtracao
    tabela: pd.DataFrame  # só troca em ações pontuais: as edições vivem no st.data_editor
    versao_tabela: int = 0
    tem_sugestoes: bool = False
    metricas_descricoes: list[MetricasLLM] = field(default_factory=list)


def main() -> None:
    st.set_page_config(page_title="Cardápio Instantâneo", page_icon="🍽️", layout="wide")
    st.title("Cardápio Instantâneo")
    st.write("Envie fotos ou o PDF do cardápio e revise o resultado antes de exportar.")
    config = Config()
    _secao_upload(config)
    extracao: Extracao | None = st.session_state.get(CHAVE_EXTRACAO)
    if extracao is not None:
        _secao_revisao(extracao, config)


def _secao_upload(config: Config) -> None:
    arquivos = st.file_uploader(
        "Até 5 fotos ou 1 PDF do cardápio", type=TIPOS_ACEITOS, accept_multiple_files=True
    )
    st.caption("Os arquivos são enviados ao provedor de IA configurado para fazer a leitura.")
    if st.button("Extrair cardápio", type="primary", disabled=not arquivos):
        _extrair([(arquivo.name, arquivo.getvalue()) for arquivo in arquivos], config)


def _extrair(arquivos: Sequence[tuple[str, bytes]], config: Config) -> None:
    with st.spinner("Lendo o cardápio..."):
        try:
            entradas = preparar_arquivos(arquivos, config.max_lado_imagem)
            resultado = extrair_entradas(entradas, criar_provedor(config), config)
        except ERROS_EXTRACAO as erro:
            st.error(f"Não foi possível ler o cardápio. {erro}")
            return
    versao = st.session_state.get(CHAVE_VERSAO, 0) + 1
    st.session_state[CHAVE_VERSAO] = versao
    st.session_state.pop(CHAVE_MENSAGEM, None)
    tabela = _criar_tabela(para_linhas(resultado.cardapio, config.limiar_confianca))
    st.session_state[CHAVE_EXTRACAO] = Extracao(versao, entradas, resultado, tabela)


def _criar_tabela(linhas: list[Linha]) -> pd.DataFrame:
    tabela = pd.DataFrame(linhas, columns=list(COLUNAS_TABELA))
    tabela["alerta"] = tabela["alerta"].map(lambda texto: f"⚠️ {texto}" if texto else "")
    return tabela


def _secao_revisao(extracao: Extracao, config: Config) -> None:
    st.divider()
    st.subheader("Revise o cardápio")
    _mostrar_painel(extracao, config)
    for aviso in extracao.resultado.avisos:
        st.warning(aviso)
    if extracao.resultado.cardapio.total_itens() == 0:
        st.warning("Nenhum item foi encontrado nesse arquivo. Você pode adicionar itens à mão.")
    coluna_arquivos, coluna_tabela = st.columns([1, 2], gap="medium")
    with coluna_arquivos:
        _mostrar_arquivos(extracao.entradas)
    with coluna_tabela:
        info = _editar_info(extracao)
        situacao = st.container()
        acoes = st.container()
        linhas = _editar_tabela(extracao)
        edicao = aplicar_edicao(
            linhas, info, _categorias_inferidas(extracao.resultado), config.limiar_confianca
        )
        with situacao:
            _mostrar_situacao(edicao)
        _acoes_de_descricoes(acoes, extracao, linhas, config)
        _secao_exportacao(edicao, extracao.entradas)


def _mostrar_painel(extracao: Extracao, config: Config) -> None:
    """Tempo e custo do cardápio: a leitura dos arquivos mais as descrições geradas."""
    operacoes = [extracao.resultado.metricas, *extracao.metricas_descricoes]
    custo = _somar_custos(operacoes)
    tempo = sum(operacao.tempo_s for operacao in operacoes)
    itens, duracao, em_dolar, em_reais = st.columns(4)
    itens.metric("Itens lidos", extracao.resultado.cardapio.total_itens())
    duracao.metric("Tempo de processamento", f"{tempo:.1f} s".replace(".", ","))
    if custo is None:
        em_dolar.metric("Custo estimado", "não cadastrado")
    else:
        em_dolar.metric("Custo estimado", f"US$ {_decimal(custo, 4)}")
        em_reais.metric(
            "Em reais",
            f"R$ {_decimal(custo * config.cotacao_usd_brl, 2)}",
            help=f"Cotação configurada: R$ {_decimal(config.cotacao_usd_brl, 2)} por dólar.",
        )
    with st.expander("Detalhes do consumo"):
        st.dataframe(
            _linhas_de_consumo(extracao), hide_index=True, width="stretch", placeholder="—"
        )
        st.caption(
            f"Estimativa pela tabela de preços do provedor, verificada em "
            f"{VERIFICADO_EM:%d/%m/%Y}. No nível gratuito da API não há cobrança."
        )


def _somar_custos(operacoes: Sequence[MetricasLLM]) -> Decimal | None:
    custos = [operacao.custo_estimado_usd for operacao in operacoes]
    if any(custo is None for custo in custos):
        return None
    return sum((custo for custo in custos if custo is not None), Decimal(0))


def _decimal(valor: Decimal, casas: int) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def _linhas_de_consumo(extracao: Extracao) -> list[dict[str, Any]]:
    linhas: list[dict[str, Any]] = [
        {
            "Etapa": f"Leitura: {arquivo.nome}",
            "Modelo": extracao.resultado.metricas.modelo,
            "Itens": arquivo.itens,
            "Tempo (s)": arquivo.tempo_s,
            "Tokens de entrada": arquivo.tokens_entrada,
            "Tokens de saída": arquivo.tokens_saida,
            "Custo (US$)": _custo_em_texto(arquivo.custo_estimado_usd),
            "Tentativas": arquivo.tentativas,
            "Erro": arquivo.erro or "",
        }
        for arquivo in extracao.resultado.metricas.arquivos
    ]
    linhas += [
        {
            "Etapa": "Descrições sugeridas",
            "Modelo": metricas.modelo,
            "Itens": None,
            "Tempo (s)": metricas.tempo_s,
            "Tokens de entrada": metricas.tokens_entrada,
            "Tokens de saída": metricas.tokens_saida,
            "Custo (US$)": _custo_em_texto(metricas.custo_estimado_usd),
            "Tentativas": metricas.tentativas,
            "Erro": "",
        }
        for metricas in extracao.metricas_descricoes
    ]
    return linhas


def _custo_em_texto(custo: Decimal | None) -> str:
    return _decimal(custo, 6) if custo is not None else "não cadastrado"


def _mostrar_arquivos(entradas: Sequence[Entrada]) -> None:
    if len(entradas) == 1:
        _mostrar_arquivo(entradas[0])
        return
    for aba, entrada in zip(st.tabs([e.nome for e in entradas]), entradas, strict=True):
        with aba:
            _mostrar_arquivo(entrada)


def _mostrar_arquivo(entrada: Entrada) -> None:
    if entrada.midia.mime == "application/pdf":
        st.info(f"PDF enviado: {entrada.nome}")
    else:
        st.image(entrada.midia.dados, caption=entrada.nome, width="stretch")


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
    colunas = [
        coluna
        for coluna in COLUNAS_TABELA
        if extracao.tem_sugestoes or coluna not in COLUNAS_SUGESTAO
    ]
    editada = st.data_editor(
        extracao.tabela.style.apply(_destacar_linha, axis=1),
        key=f"tabela_{extracao.versao}_{extracao.versao_tabela}",
        column_config=COLUNAS_TABELA,
        column_order=colunas,
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


def _acoes_de_descricoes(
    area: DeltaGenerator, extracao: Extracao, linhas: list[Linha], config: Config
) -> None:
    gerar, usar_todas, manter_originais = area.columns(3)
    if gerar.button("Gerar descrições sugeridas", width="stretch"):
        with area, st.spinner("Escrevendo as descrições..."):
            _gerar_sugestoes(area, extracao, linhas, config)
    if extracao.tem_sugestoes:
        if usar_todas.button("Usar todas as sugestões", width="stretch"):
            _marcar_uso_das_sugestoes(extracao, linhas, usar=True)
        if manter_originais.button("Manter todas as originais", width="stretch"):
            _marcar_uso_das_sugestoes(extracao, linhas, usar=False)
    mensagem = st.session_state.get(CHAVE_MENSAGEM)
    if mensagem:
        area.info(mensagem)


def _gerar_sugestoes(
    area: DeltaGenerator, extracao: Extracao, linhas: list[Linha], config: Config
) -> None:
    itens = _itens_para_descrever(linhas)
    if not itens:
        area.warning("Não há itens para descrever.")
        return
    try:
        resultado = gerar_descricoes(itens, criar_provedor(config.para_descricoes()), config)
    except ERROS_EXTRACAO as erro:
        area.error(f"Não foi possível gerar as descrições. {erro}")
        return
    for indice, linha in enumerate(linhas):
        linha["descricao_sugerida"] = resultado.sugestoes.get(indice, "")
        linha["usar_sugestao"] = False
    extracao.metricas_descricoes.append(resultado.metricas)
    extracao.tem_sugestoes = True
    st.session_state[CHAVE_MENSAGEM] = _resumir_sugestoes(resultado)
    _trocar_tabela(extracao, linhas)


def _itens_para_descrever(linhas: Sequence[Linha]) -> list[ItemParaDescrever]:
    """Lê direto da tabela: as sugestões não dependem de os preços estarem corretos."""
    return [
        ItemParaDescrever(
            id=indice,
            categoria=linha.get("categoria") or "",
            nome=linha["nome"],
            descricao_original=linha.get("descricao") or None,
        )
        for indice, linha in enumerate(linhas)
        if linha.get("nome")
    ]


def _resumir_sugestoes(resultado: ResultadoDescricoes) -> str:
    texto = f"{len(resultado.sugestoes)} descrição(ões) sugerida(s)."
    if resultado.descartadas:
        texto += (
            f" {len(resultado.descartadas)} descartada(s) porque mudavam informação do prato: "
            "esses itens ficam só com a descrição original."
        )
    return texto + " Compare com a original e marque **Usar sugestão** nas que preferir."


def _marcar_uso_das_sugestoes(extracao: Extracao, linhas: list[Linha], usar: bool) -> None:
    for linha in linhas:
        linha["usar_sugestao"] = usar and bool(linha.get("descricao_sugerida"))
    _trocar_tabela(extracao, linhas)


def _trocar_tabela(extracao: Extracao, linhas: list[Linha]) -> None:
    """Recria a tabela preservando as edições, com uma nova chave para o st.data_editor."""
    extracao.tabela = pd.DataFrame(
        [_linha_preenchida(linha) for linha in linhas], columns=list(COLUNAS_TABELA)
    )
    extracao.versao_tabela += 1
    st.rerun()


def _linha_preenchida(linha: Linha) -> Linha:
    """Trata células vazias de linhas novas: a tabela recriada precisa de tipos consistentes."""
    preenchida = dict(linha)
    for coluna in (*COLUNAS_TEXTO, "alerta", "descricao_sugerida"):
        preenchida[coluna] = linha.get(coluna) or ""
    preenchida["conferido"] = bool(linha.get("conferido"))
    preenchida["usar_sugestao"] = bool(linha.get("usar_sugestao"))
    alergenicos = linha.get("alergenicos")
    preenchida["alergenicos"] = [] if alergenicos is None else list(alergenicos)
    return preenchida


def _secao_exportacao(edicao: CardapioEditado, entradas: Sequence[Entrada]) -> None:
    cardapio = edicao.cardapio
    pronto = cardapio is not None
    json_saida = exportar_json(cardapio, edicao.pendencias, edicao.descricoes) if cardapio else b""
    csv_saida = exportar_csv(cardapio, edicao.pendencias, edicao.descricoes) if cardapio else b""
    base = Path(entradas[0].nome).stem if len(entradas) == 1 else BASE_ARQUIVO_VARIOS
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
