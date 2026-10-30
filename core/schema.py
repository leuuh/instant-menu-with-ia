"""Modelos Pydantic do cardápio.

Duas camadas:
- ``ExtracaoCardapio``: contrato exato do prompts/extracao.md; o JSON Schema
  enviado ao LLM é gerado a partir dela.
- ``ResultadoExtracao``: o que a aplicação devolve (extração + revisão + métricas).
  O LLM nunca preenche essa camada.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema

DecimalComoNumero = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

# Preço em reais. Zero é proibido: preço ilegível ou ausente é null.
Preco = Annotated[
    Decimal,
    Field(gt=0, max_digits=8, decimal_places=2),
    WithJsonSchema({"type": "number"}),
    PlainSerializer(float, return_type=float, when_used="json"),
]

NomeNaoVazio = Annotated[str, Field(min_length=1)]


class Base(BaseModel):
    """Base dos modelos do LLM: rejeita campos extras e apara espaços."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Alergenico(StrEnum):
    """Alergênicos prováveis (sugestão, não certeza)."""

    GLUTEN = "gluten"
    LACTOSE = "lactose"
    OVO = "ovo"
    AMENDOIM = "amendoim"
    CASTANHAS = "castanhas"
    FRUTOS_DO_MAR = "frutos_do_mar"
    SOJA = "soja"


class InfoRestaurante(Base):
    nome: str | None
    telefone: str | None
    horario: str | None


class OpcaoPreco(Base):
    """Variação (tamanho/versão) ou adicional, cada um com seu preço."""

    nome: NomeNaoVazio
    preco: Preco | None


class ItemExtraido(Base):
    nome: NomeNaoVazio
    descricao_original: str | None
    preco: Preco | None  # null quando há variações ou o preço é ilegível
    variacoes: list[OpcaoPreco]
    adicionais: list[OpcaoPreco]
    alergenicos_provaveis: list[Alergenico]
    confianca: float = Field(ge=0, le=1)
    observacao: str | None


class CategoriaExtraida(Base):
    nome: NomeNaoVazio
    categoria_inferida: bool
    itens: list[ItemExtraido]


class ExtracaoCardapio(Base):
    """Cardápio extraído das imagens."""  # docstring vira description no schema do LLM

    info_restaurante: InfoRestaurante
    categorias: list[CategoriaExtraida]

    def total_itens(self) -> int:
        """Quantidade de itens em todas as categorias."""
        return sum(len(categoria.itens) for categoria in self.categorias)


# ---- camada da aplicação ----


class MotivoRevisao(StrEnum):
    CONFIANCA_BAIXA = "confianca_baixa"
    PRECO_AUSENTE = "preco_ausente"
    PRECO_VARIACAO_AUSENTE = "preco_variacao_ausente"
    PRECO_ADICIONAL_AUSENTE = "preco_adicional_ausente"


class ItemParaRevisao(BaseModel):
    categoria: str
    indice_item: int
    nome: str
    motivos: list[MotivoRevisao]


class MetricasArquivo(BaseModel):
    """Consumo da leitura de um arquivo."""

    nome: str
    itens: int
    tokens_entrada: int
    tokens_saida: int
    custo_estimado_usd: DecimalComoNumero | None
    tempo_s: float
    tentativas: int
    erro: str | None = None


class MetricasLLM(BaseModel):
    """Consumo de uma operação; em ``arquivos``, o detalhe quando há mais de um arquivo."""

    provedor: str
    modelo: str
    prompt_sha: str
    tokens_entrada: int
    tokens_saida: int  # inclui tokens de raciocínio, cobrados como saída
    custo_estimado_usd: DecimalComoNumero | None  # None = modelo sem preço na tabela
    tempo_s: float
    tentativas: int
    arquivos: list[MetricasArquivo] = Field(default_factory=list)


class ResultadoExtracao(BaseModel):
    cardapio: ExtracaoCardapio
    revisao: list[ItemParaRevisao]
    metricas: MetricasLLM
    avisos: list[str] = Field(default_factory=list)  # arquivos que não puderam ser lidos


# ---- schema para o LLM ----


def schema_para_llm(modelo: type[BaseModel]) -> dict[str, Any]:
    """Gera JSON Schema sem $ref/$defs e com nulos como array de tipos."""
    bruto = modelo.model_json_schema()
    definicoes = bruto.pop("$defs", {})
    resultado: dict[str, Any] = _normalizar(bruto, definicoes)
    return resultado


def _normalizar(no: Any, definicoes: dict[str, Any]) -> Any:
    if isinstance(no, list):
        return [_normalizar(filho, definicoes) for filho in no]
    if not isinstance(no, dict):
        return no
    if "$ref" in no:
        nome = no["$ref"].rsplit("/", 1)[-1]
        return _normalizar(definicoes[nome], definicoes)
    normalizado = {chave: _normalizar(valor, definicoes) for chave, valor in no.items()}
    return _achatar_nulo(normalizado)


def _achatar_nulo(no: dict[str, Any]) -> dict[str, Any]:
    """Converte anyOf [X, null] em X com type [tipo, "null"]."""
    opcoes = no.get("anyOf")
    if not isinstance(opcoes, list) or len(opcoes) != 2:
        return no
    nao_nulas = [opcao for opcao in opcoes if opcao.get("type") != "null"]
    if len(nao_nulas) != 1 or not isinstance(nao_nulas[0].get("type"), str):
        return no
    resto = {chave: valor for chave, valor in no.items() if chave != "anyOf"}
    alvo = {**nao_nulas[0], "type": [nao_nulas[0]["type"], "null"]}
    return {**alvo, **resto}
