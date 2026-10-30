"""Tabela de preços dos modelos e cálculo de custo estimado (USD)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

FONTE = "https://ai.google.dev/gemini-api/docs/pricing"
VERIFICADO_EM = date(2026, 10, 29)

UM_MILHAO = Decimal(1_000_000)


@dataclass(frozen=True)
class PrecoModelo:
    """Preço por milhão de tokens, válido a partir de ``vigente_desde``."""

    vigente_desde: date
    entrada_usd_mtok: Decimal
    saida_usd_mtok: Decimal


TabelaPrecos = Mapping[str, Sequence[PrecoModelo]]

# Faixas em ordem cronológica. Tokens de raciocínio são cobrados como saída.
TABELA: TabelaPrecos = {
    "gemini-3.8-flash": (
        PrecoModelo(date.min, Decimal("0.75"), Decimal("3.75")),
        PrecoModelo(date(2027, 1, 1), Decimal("1.50"), Decimal("7.50")),
    ),
    "gemini-3.5-flash-lite": (PrecoModelo(date.min, Decimal("0.30"), Decimal("2.50")),),
}


def preco_vigente(
    modelo: str, dia: date | None = None, tabela: TabelaPrecos = TABELA
) -> PrecoModelo | None:
    """Faixa de preço válida no dia (hoje por padrão), ou None se o modelo não está na tabela."""
    dia = dia or date.today()
    faixas = [faixa for faixa in tabela.get(modelo, ()) if faixa.vigente_desde <= dia]
    return faixas[-1] if faixas else None


def calcular_custo(
    modelo: str,
    tokens_entrada: int,
    tokens_saida: int,
    dia: date | None = None,
    tabela: TabelaPrecos = TABELA,
) -> Decimal | None:
    """Custo estimado em USD com 6 casas, ou None se o modelo não tem preço cadastrado."""
    preco = preco_vigente(modelo, dia, tabela)
    if preco is None:
        return None
    custo = (
        tokens_entrada * preco.entrada_usd_mtok + tokens_saida * preco.saida_usd_mtok
    ) / UM_MILHAO
    return custo.quantize(Decimal("0.000001"))
