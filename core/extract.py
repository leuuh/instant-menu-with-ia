"""Extração do cardápio: lê cada arquivo em paralelo, une os resultados e registra as métricas."""

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.arquivos import ArquivoInvalidoErro, Entrada, carregar_arquivos
from core.chamada import (
    Consumo,
    RespostaInvalidaErro,
    carregar_prompt,
    chamar_validando,
    sha_curto,
)
from core.config import Config, ConfigErro
from core.precos import calcular_custo
from core.providers.base import ProvedorErro, ProvedorLLM
from core.registro import registrar_extracao
from core.revisao import itens_para_revisao
from core.schema import ExtracaoCardapio, MetricasArquivo, MetricasLLM, ResultadoExtracao
from core.unir import unir_cardapios

# Falhas previstas: a interface mostra a mensagem em vez de um traceback.
ERROS_EXTRACAO = (ConfigErro, ArquivoInvalidoErro, ProvedorErro, RespostaInvalidaErro)


@dataclass(frozen=True)
class _Leitura:
    """Resultado de um arquivo: o cardápio lido ou o erro, sempre com o consumo."""

    nome: str
    metricas: MetricasLLM
    cardapio: ExtracaoCardapio | None = None
    erro: ProvedorErro | RespostaInvalidaErro | None = None


def extrair_cardapio(caminho: Path, provedor: ProvedorLLM, config: Config) -> ResultadoExtracao:
    """Extrai o cardápio de um arquivo JPG, PNG ou PDF."""
    return extrair_arquivos([caminho], provedor, config)


def extrair_arquivos(
    caminhos: Sequence[Path], provedor: ProvedorLLM, config: Config
) -> ResultadoExtracao:
    """Extrai o cardápio de 1 a 5 imagens ou de 1 PDF lidos do disco."""
    return extrair_entradas(carregar_arquivos(caminhos, config.max_lado_imagem), provedor, config)


def extrair_entradas(
    entradas: Sequence[Entrada], provedor: ProvedorLLM, config: Config
) -> ResultadoExtracao:
    """Lê os arquivos em paralelo e une o que deu certo; só falha se nenhum puder ser lido."""
    inicio = time.perf_counter()
    instrucoes = carregar_prompt("extracao.md")
    leituras = _ler_em_paralelo(entradas, instrucoes, provedor, config)
    metricas = _somar_metricas(leituras, provedor, sha_curto(instrucoes), inicio)
    origem = ", ".join(entrada.nome for entrada in entradas)
    lidos = [leitura.cardapio for leitura in leituras if leitura.cardapio is not None]
    if not lidos:
        erro = next(leitura.erro for leitura in leituras if leitura.erro is not None)
        _registrar(origem, metricas, config, erro=erro)
        raise erro
    cardapio = unir_cardapios(lidos)
    resultado = ResultadoExtracao(
        cardapio=cardapio,
        revisao=itens_para_revisao(cardapio, config.limiar_confianca),
        metricas=metricas,
        avisos=_avisos(leituras),
    )
    _registrar(origem, metricas, config, resultado=resultado)
    return resultado


def _ler_em_paralelo(
    entradas: Sequence[Entrada], instrucoes: str, provedor: ProvedorLLM, config: Config
) -> list[_Leitura]:
    with ThreadPoolExecutor(
        max_workers=min(len(entradas), config.max_chamadas_paralelas)
    ) as executor:
        return list(
            executor.map(lambda entrada: _ler(entrada, instrucoes, provedor, config), entradas)
        )


def _ler(entrada: Entrada, instrucoes: str, provedor: ProvedorLLM, config: Config) -> _Leitura:
    consumo = Consumo(provedor, sha_curto(instrucoes))
    try:
        cardapio = chamar_validando(
            ExtracaoCardapio, instrucoes, [entrada.midia], consumo, config.max_correcoes
        )
    except (ProvedorErro, RespostaInvalidaErro) as erro:
        return _Leitura(entrada.nome, consumo.metricas(), erro=erro)
    return _Leitura(entrada.nome, consumo.metricas(), cardapio=cardapio)


def _somar_metricas(
    leituras: Sequence[_Leitura], provedor: ProvedorLLM, prompt_sha: str, inicio: float
) -> MetricasLLM:
    """Tokens somados entre os arquivos; o tempo é o decorrido, porque as chamadas são paralelas."""
    tokens_entrada = sum(leitura.metricas.tokens_entrada for leitura in leituras)
    tokens_saida = sum(leitura.metricas.tokens_saida for leitura in leituras)
    custo: Decimal | None = calcular_custo(provedor.modelo, tokens_entrada, tokens_saida)
    return MetricasLLM(
        provedor=provedor.nome,
        modelo=provedor.modelo,
        prompt_sha=prompt_sha,
        tokens_entrada=tokens_entrada,
        tokens_saida=tokens_saida,
        custo_estimado_usd=custo,
        tempo_s=round(time.perf_counter() - inicio, 2),
        tentativas=sum(leitura.metricas.tentativas for leitura in leituras),
        arquivos=[_metricas_do_arquivo(leitura) for leitura in leituras],
    )


def _metricas_do_arquivo(leitura: _Leitura) -> MetricasArquivo:
    metricas = leitura.metricas
    return MetricasArquivo(
        nome=leitura.nome,
        itens=leitura.cardapio.total_itens() if leitura.cardapio else 0,
        tokens_entrada=metricas.tokens_entrada,
        tokens_saida=metricas.tokens_saida,
        custo_estimado_usd=metricas.custo_estimado_usd,
        tempo_s=metricas.tempo_s,
        tentativas=metricas.tentativas,
        erro=_primeira_linha(leitura.erro),
    )


def _avisos(leituras: Sequence[_Leitura]) -> list[str]:
    """Nunca descarta um arquivo em silêncio: o dono precisa saber o que ficou de fora."""
    avisos: list[str] = []
    for leitura in leituras:
        if leitura.erro is not None:
            avisos.append(
                f"{leitura.nome}: não foi possível ler, e os itens desse arquivo não estão "
                f"na tabela. {_primeira_linha(leitura.erro)}"
            )
        elif len(leituras) > 1 and leitura.cardapio and leitura.cardapio.total_itens() == 0:
            avisos.append(f"{leitura.nome}: nenhum item encontrado nesse arquivo.")
    return avisos


def _primeira_linha(erro: Exception | None) -> str | None:
    return str(erro).splitlines()[0] if erro is not None else None


def _registrar(
    origem: str,
    metricas: MetricasLLM,
    config: Config,
    resultado: ResultadoExtracao | None = None,
    erro: Exception | None = None,
) -> None:
    evento: dict[str, Any] = {
        "tipo": "extracao",
        "origem": origem,
        **metricas.model_dump(mode="json"),
    }
    if resultado is not None:
        evento["n_itens"] = resultado.cardapio.total_itens()
        evento["n_revisao"] = len(resultado.revisao)
        evento["n_avisos"] = len(resultado.avisos)
    evento["sucesso"] = erro is None
    if erro is not None:
        evento["erro"] = f"{type(erro).__name__}: {erro}"
    registrar_extracao(evento, config.dir_logs)
