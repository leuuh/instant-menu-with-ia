"""Chamada ao LLM com validação Pydantic e correção, usada na extração e nas descrições."""

import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from core.config import RAIZ_PROJETO
from core.precos import calcular_custo
from core.providers.base import Correcao, Midia, ProvedorLLM, RespostaLLM
from core.schema import MetricasLLM, schema_para_llm

DIR_PROMPTS = RAIZ_PROJETO / "prompts"
MAX_CARACTERES_ENTRADA_ERRO = 80

T = TypeVar("T", bound=BaseModel)


class RespostaInvalidaErro(Exception):
    """O modelo não produziu JSON válido nem após as correções."""

    def __init__(self, mensagem: str, metricas: MetricasLLM) -> None:
        super().__init__(mensagem)
        self.metricas = metricas


@dataclass
class Consumo:
    """Tokens e tentativas somados ao longo das chamadas."""

    provedor: ProvedorLLM
    prompt_sha: str
    inicio: float = field(default_factory=time.perf_counter)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tentativas: int = 0

    def registrar(self, resposta: RespostaLLM) -> None:
        self.tokens_entrada += resposta.tokens_entrada
        self.tokens_saida += resposta.tokens_saida
        self.tentativas += 1

    def metricas(self) -> MetricasLLM:
        return MetricasLLM(
            provedor=self.provedor.nome,
            modelo=self.provedor.modelo,
            prompt_sha=self.prompt_sha,
            tokens_entrada=self.tokens_entrada,
            tokens_saida=self.tokens_saida,
            custo_estimado_usd=calcular_custo(
                self.provedor.modelo, self.tokens_entrada, self.tokens_saida
            ),
            tempo_s=round(time.perf_counter() - self.inicio, 2),
            tentativas=self.tentativas,
        )


def carregar_prompt(nome: str) -> str:
    """Lê um prompt versionado de prompts/."""
    return (DIR_PROMPTS / nome).read_text(encoding="utf-8")


def sha_curto(texto: str) -> str:
    """8 primeiros caracteres do sha256: identifica a versão do prompt nos logs."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8]


def formatar_erros(erro: ValidationError) -> str:
    """Erros de validação em linhas curtas, no formato que o modelo consegue corrigir."""
    linhas = []
    for detalhe in erro.errors(include_url=False):
        local = ".".join(str(parte) for parte in detalhe["loc"]) or "(raiz)"
        recebido = repr(detalhe.get("input"))[:MAX_CARACTERES_ENTRADA_ERRO]
        linhas.append(f"- {local}: {detalhe['msg']} (recebido: {recebido})")
    return "\n".join(linhas)


def chamar_validando(
    modelo: type[T],
    instrucoes: str,
    midias: Sequence[Midia],
    consumo: Consumo,
    max_correcoes: int,
) -> T:
    """Chama o LLM e, se a validação falhar, reenvia o erro até ``max_correcoes`` vezes."""
    schema = schema_para_llm(modelo)
    modelo_correcao = carregar_prompt("correcao.md")
    correcoes: list[Correcao] = []
    for _ in range(max_correcoes + 1):
        resposta = consumo.provedor.gerar_json(
            instrucoes=instrucoes, midias=midias, schema=schema, correcoes=correcoes
        )
        consumo.registrar(resposta)
        try:
            return modelo.model_validate_json(resposta.texto)
        except ValidationError as erro:
            mensagem = modelo_correcao.replace("{erros}", formatar_erros(erro))
            correcoes.append(Correcao(resposta.texto, mensagem))
    raise RespostaInvalidaErro(
        f"JSON inválido após {consumo.tentativas} tentativas:\n{correcoes[-1].mensagem_erro}",
        consumo.metricas(),
    )
