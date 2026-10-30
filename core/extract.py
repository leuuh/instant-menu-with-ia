"""Extração do cardápio: chamada ao LLM, validação Pydantic e correção com retry."""

import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.arquivos import ArquivoInvalidoErro, carregar_arquivo
from core.config import RAIZ_PROJETO, Config, ConfigErro
from core.precos import calcular_custo
from core.providers.base import Correcao, Midia, ProvedorErro, ProvedorLLM, RespostaLLM
from core.registro import registrar_extracao
from core.revisao import itens_para_revisao
from core.schema import (
    ExtracaoCardapio,
    MetricasExtracao,
    ResultadoExtracao,
    schema_para_llm,
)

DIR_PROMPTS = RAIZ_PROJETO / "prompts"
MAX_CARACTERES_ENTRADA_ERRO = 80


class ExtracaoInvalidaErro(Exception):
    """O modelo não produziu JSON válido nem após as correções."""

    def __init__(self, mensagem: str, metricas: MetricasExtracao) -> None:
        super().__init__(mensagem)
        self.metricas = metricas


# Falhas previstas: a interface mostra a mensagem em vez de um traceback.
ERROS_EXTRACAO = (ConfigErro, ArquivoInvalidoErro, ProvedorErro, ExtracaoInvalidaErro)


@dataclass
class _Consumo:
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

    def metricas(self) -> MetricasExtracao:
        return MetricasExtracao(
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


def extrair_cardapio(caminho: Path, provedor: ProvedorLLM, config: Config) -> ResultadoExtracao:
    """Extrai o cardápio de um arquivo JPG, PNG ou PDF."""
    midia = carregar_arquivo(caminho, config.max_lado_imagem)
    return extrair_de_midias([midia], provedor, config, origem=caminho.name)


def extrair_de_midias(
    midias: Sequence[Midia], provedor: ProvedorLLM, config: Config, origem: str = ""
) -> ResultadoExtracao:
    """Chama o LLM com até ``config.max_correcoes`` correções e registra o resultado no log."""
    instrucoes = carregar_prompt("extracao.md")
    consumo = _Consumo(provedor, sha_curto(instrucoes))
    try:
        cardapio = _chamar_com_correcoes(instrucoes, midias, consumo, config.max_correcoes)
    except (ProvedorErro, ExtracaoInvalidaErro) as erro:
        _registrar(origem, consumo.metricas(), config, erro=erro)
        raise
    resultado = ResultadoExtracao(
        cardapio=cardapio,
        revisao=itens_para_revisao(cardapio, config.limiar_confianca),
        metricas=consumo.metricas(),
    )
    _registrar(origem, resultado.metricas, config, resultado=resultado)
    return resultado


def _chamar_com_correcoes(
    instrucoes: str, midias: Sequence[Midia], consumo: _Consumo, max_correcoes: int
) -> ExtracaoCardapio:
    schema = schema_para_llm(ExtracaoCardapio)
    modelo_correcao = carregar_prompt("correcao.md")
    correcoes: list[Correcao] = []
    for _ in range(max_correcoes + 1):
        resposta = consumo.provedor.gerar_json(
            instrucoes=instrucoes, midias=midias, schema=schema, correcoes=correcoes
        )
        consumo.registrar(resposta)
        try:
            return ExtracaoCardapio.model_validate_json(resposta.texto)
        except ValidationError as erro:
            mensagem = modelo_correcao.replace("{erros}", formatar_erros(erro))
            correcoes.append(Correcao(resposta.texto, mensagem))
    raise ExtracaoInvalidaErro(
        f"JSON inválido após {consumo.tentativas} tentativas:\n{correcoes[-1].mensagem_erro}",
        consumo.metricas(),
    )


def _registrar(
    origem: str,
    metricas: MetricasExtracao,
    config: Config,
    resultado: ResultadoExtracao | None = None,
    erro: Exception | None = None,
) -> None:
    evento: dict[str, Any] = {"origem": origem, **metricas.model_dump(mode="json")}
    if resultado is not None:
        evento["n_itens"] = resultado.cardapio.total_itens()
        evento["n_revisao"] = len(resultado.revisao)
    evento["sucesso"] = erro is None
    if erro is not None:
        evento["erro"] = f"{type(erro).__name__}: {erro}"
    registrar_extracao(evento, config.dir_logs)
