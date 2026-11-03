from datetime import date
from decimal import Decimal

from core.precos import PrecoModelo, calcular_custo, preco_vigente
from core.providers.gemini import ProvedorGemini

TABELA_TESTE = {
    "modelo-x": (
        PrecoModelo(date.min, Decimal("1.00"), Decimal("4.00")),
        PrecoModelo(date(2027, 1, 1), Decimal("2.00"), Decimal("8.00")),
    )
}


def test_custo_por_milhao_de_tokens() -> None:
    custo = calcular_custo("modelo-x", 2_000, 500, date(2026, 11, 1), TABELA_TESTE)
    # 2000 * 1.00 / 1M + 500 * 4.00 / 1M = 0.002 + 0.002
    assert custo == Decimal("0.004000")


def test_preco_muda_na_data_de_vigencia() -> None:
    assert (
        preco_vigente("modelo-x", date(2026, 12, 31), TABELA_TESTE) == TABELA_TESTE["modelo-x"][0]
    )
    assert calcular_custo("modelo-x", 1_000_000, 0, date(2027, 1, 1), TABELA_TESTE) == Decimal(
        "2.000000"
    )


def test_modelo_sem_preco_devolve_none() -> None:
    assert calcular_custo("modelo-desconhecido", 100, 100) is None


def test_tabela_real_tem_o_modelo_padrao() -> None:
    assert preco_vigente(ProvedorGemini.modelo_padrao, date(2026, 10, 29)) is not None
