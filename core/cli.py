"""Linha de comando: python -m core.cli extrair foto.jpg --saida cardapio.json"""

import argparse
import sys
from pathlib import Path

from core.config import Config, ConfigErro
from core.extract import ExtracaoInvalidaErro, extrair_cardapio
from core.imagens import ImagemInvalidaErro
from core.providers import criar_provedor
from core.providers.base import ProvedorErro
from core.schema import ResultadoExtracao

ERROS_ESPERADOS = (ConfigErro, ImagemInvalidaErro, ProvedorErro, ExtracaoInvalidaErro)


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.cli", description="Cardápio Instantâneo: foto de cardápio para JSON."
    )
    comandos = parser.add_subparsers(dest="comando", required=True)
    extrair = comandos.add_parser("extrair", help="extrai o cardápio de uma imagem JPG/PNG")
    extrair.add_argument("imagem", type=Path, help="caminho da foto do cardápio")
    extrair.add_argument("--saida", type=Path, help="arquivo JSON de saída (padrão: stdout)")
    extrair.add_argument("--provedor", help="sobrescreve LLM_PROVIDER do .env")
    extrair.add_argument("--modelo", help="sobrescreve LLM_MODEL do .env")
    return parser


def resumo(resultado: ResultadoExtracao) -> str:
    """Texto curto com contagens, itens em revisão e métricas."""
    cardapio, metricas = resultado.cardapio, resultado.metricas
    custo = (
        f"US$ {metricas.custo_estimado_usd:.6f}"
        if metricas.custo_estimado_usd is not None
        else "sem preço cadastrado"
    )
    linhas = [
        f"Cardápio extraído: {len(cardapio.categorias)} categorias, {cardapio.total_itens()} itens",
        f"Itens para revisão: {len(resultado.revisao)}",
    ]
    linhas += [
        f"  - {item.categoria} / {item.nome}: {', '.join(item.motivos)}"
        for item in resultado.revisao
    ]
    linhas.append(
        f"Modelo: {metricas.provedor}/{metricas.modelo} | tentativas: {metricas.tentativas} | "
        f"tokens: {metricas.tokens_entrada} entrada / {metricas.tokens_saida} saída | "
        f"custo: {custo} | tempo: {metricas.tempo_s:.1f} s"
    )
    return "\n".join(linhas)


def _config_com_sobrescritas(args: argparse.Namespace) -> Config:
    config = Config()
    sobrescritas = {"llm_provider": args.provedor, "llm_model": args.modelo}
    return config.model_copy(update={k: v for k, v in sobrescritas.items() if v})


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = criar_parser().parse_args(argv)
    if not args.imagem.is_file():
        print(f"Erro: arquivo não encontrado: {args.imagem}", file=sys.stderr)
        return 1
    config = _config_com_sobrescritas(args)
    try:
        resultado = extrair_cardapio(args.imagem, criar_provedor(config), config)
    except ERROS_ESPERADOS as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    json_saida = resultado.model_dump_json(indent=2)
    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(json_saida, encoding="utf-8")
        print(f"JSON salvo em {args.saida}", file=sys.stderr)
    else:
        print(json_saida)
    print(resumo(resultado), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
