"""Descrições sugeridas: texto mais atrativo, sem inventar nada sobre o prato.

O prompt proíbe acrescentar informação, mas o modelo pode desobedecer (ver docs/decisoes.md).
Por isso cada sugestão passa por uma checagem em código e é descartada se trouxer um número,
um ingrediente alergênico ou uma promessa que não estão no cardápio, ou se omitir um
alergênico citado na descrição original. A checagem é uma lista de termos, não uma garantia:
quem decide usar a sugestão é sempre o dono.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import Field

from core.chamada import Consumo, carregar_prompt, chamar_validando, sha_curto
from core.config import Config
from core.providers.base import ProvedorLLM
from core.registro import registrar_extracao
from core.schema import Base, MetricasLLM, NomeNaoVazio
from core.unir import normalizar

MAX_CARACTERES = 160

# Começos de palavra, já sem acentos: "queij" pega queijo, queijos e queijinho.
TERMOS_ALERGENICOS = (
    "gluten",
    "trigo",
    "pao",
    "lactose",
    "leite",
    "iogurte",
    "queij",
    "requeij",
    "mussarel",
    "manteig",
    "creme",
    "ovo",
    "amendoim",
    "castanh",
    "noz",
    "camar",
    "lagost",
    "soja",
    "shoyu",
)
TERMOS_PROMESSA = (
    "artesana",
    "casei",
    "fresc",
    "premium",
    "organic",
    "importad",
    "gourmet",
    "crocant",
    "cremos",
    "maci",
    "suculent",
)
EXPRESSOES_PROMESSA = ("feito na hora", "feita na hora", "receita da casa")


class DescricaoSugerida(Base):
    id: int = Field(ge=0)
    descricao: NomeNaoVazio


class DescricoesSugeridas(Base):
    """Descrições sugeridas para os itens do cardápio."""

    descricoes: list[DescricaoSugerida]


@dataclass(frozen=True)
class ItemParaDescrever:
    id: int
    categoria: str
    nome: str
    descricao_original: str | None = None


@dataclass(frozen=True)
class ResultadoDescricoes:
    sugestoes: dict[int, str]
    metricas: MetricasLLM
    descartadas: dict[int, str] = field(default_factory=dict)  # id -> motivo


def gerar_descricoes(
    itens: Sequence[ItemParaDescrever], provedor: ProvedorLLM, config: Config
) -> ResultadoDescricoes:
    """Gera as sugestões e descarta as que acrescentam ou omitem informação."""
    modelo_prompt = carregar_prompt("descricoes.md")
    consumo = Consumo(provedor, sha_curto(modelo_prompt))
    instrucoes = f"{modelo_prompt}\n{_listar_itens(itens)}\n"
    resposta = chamar_validando(DescricoesSugeridas, instrucoes, [], consumo, config.max_correcoes)
    por_id = {item.id: item for item in itens}
    sugestoes: dict[int, str] = {}
    descartadas: dict[int, str] = {}
    for sugerida in resposta.descricoes:
        item = por_id.get(sugerida.id)
        if item is None:
            continue
        motivo = motivo_para_descartar(sugerida.descricao, item)
        if motivo:
            descartadas[item.id] = motivo
        else:
            sugestoes[item.id] = sugerida.descricao.strip()
    metricas = consumo.metricas()
    _registrar(len(itens), sugestoes, descartadas, metricas, config)
    return ResultadoDescricoes(sugestoes, metricas, descartadas)


def motivo_para_descartar(sugestao: str, item: ItemParaDescrever) -> str | None:
    """Explica por que a sugestão não pode ser usada, ou None se passou nas checagens."""
    if len(sugestao) > MAX_CARACTERES:
        return f"passou de {MAX_CARACTERES} caracteres"
    fonte = normalizar(f"{item.categoria} {item.nome} {item.descricao_original or ''}")
    texto = normalizar(sugestao)
    numeros_novos = set(re.findall(r"\d+", texto)) - set(re.findall(r"\d+", fonte))
    if numeros_novos:
        return f"acrescentou o número {sorted(numeros_novos)[0]}"
    for termo in (*TERMOS_ALERGENICOS, *TERMOS_PROMESSA):
        if _tem_termo(texto, termo) and not _tem_termo(fonte, termo):
            return f"acrescentou '{termo}'"
    for expressao in EXPRESSOES_PROMESSA:
        if expressao in texto and expressao not in fonte:
            return f"acrescentou '{expressao}'"
    original = normalizar(item.descricao_original or "")
    for termo in TERMOS_ALERGENICOS:
        if _tem_termo(original, termo) and not _tem_termo(texto, termo):
            return f"omitiu '{termo}', que está na descrição original"
    return None


def _tem_termo(texto: str, termo: str) -> bool:
    palavras = ("pao" if palavra == "paes" else palavra for palavra in texto.split())
    return any(palavra.startswith(termo) for palavra in palavras)


def _listar_itens(itens: Sequence[ItemParaDescrever]) -> str:
    return json.dumps(
        [
            {
                "id": item.id,
                "categoria": item.categoria,
                "nome": item.nome,
                "descricao_original": item.descricao_original,
            }
            for item in itens
        ],
        ensure_ascii=False,
    )


def _registrar(
    n_itens: int,
    sugestoes: dict[int, str],
    descartadas: dict[int, str],
    metricas: MetricasLLM,
    config: Config,
) -> None:
    registrar_extracao(
        {
            "tipo": "descricoes",
            **metricas.model_dump(mode="json"),
            "n_itens": n_itens,
            "n_sugestoes": len(sugestoes),
            "n_descartadas": len(descartadas),
            "sucesso": True,
        },
        config.dir_logs,
    )
