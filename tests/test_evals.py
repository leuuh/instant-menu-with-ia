import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.config import Config
from core.providers.base import Midia
from core.providers.fake import ProvedorFake
from core.schema import (
    CategoriaExtraida,
    ExtracaoCardapio,
    InfoRestaurante,
    ItemExtraido,
    ItemParaRevisao,
    MetricasLLM,
    MotivoRevisao,
    OpcaoPreco,
    ResultadoExtracao,
)
from evals import run_evals
from evals.metricas import (
    Contagem,
    Gabarito,
    ItemGabarito,
    ItemObtido,
    carregar_gabarito,
    casar,
    comparar,
    similaridade,
)


def _esperado(
    nome: str,
    preco: str | None = "10.00",
    categoria: str = "Lanches",
    variacoes: tuple[str, ...] = (),
    ilegivel: bool = False,
) -> ItemGabarito:
    return ItemGabarito(
        categoria=categoria,
        nome=nome,
        preco=Decimal(preco) if preco else None,
        variacoes=tuple(Decimal(v) for v in variacoes),
        ilegivel=ilegivel,
    )


def _extraido(
    nome: str, preco: str | None = "10.00", variacoes: tuple[str, ...] = ()
) -> ItemExtraido:
    return ItemExtraido(
        nome=nome,
        descricao_original=None,
        preco=Decimal(preco) if preco else None,
        variacoes=[OpcaoPreco(nome=f"V{n}", preco=Decimal(v)) for n, v in enumerate(variacoes)],
        adicionais=[],
        alergenicos_provaveis=[],
        confianca=0.95,
        observacao=None,
    )


def _obtido(nome: str, categoria: str = "Lanches") -> ItemObtido:
    return ItemObtido(categoria, _extraido(nome), em_revisao=False)


def _resultado(
    itens: list[tuple[str, ItemExtraido]], em_revisao: tuple[str, ...] = ()
) -> ResultadoExtracao:
    categorias: dict[str, list[ItemExtraido]] = {}
    for categoria, item in itens:
        categorias.setdefault(categoria, []).append(item)
    cardapio = ExtracaoCardapio(
        info_restaurante=InfoRestaurante(nome=None, telefone=None, horario=None),
        categorias=[
            CategoriaExtraida(nome=nome, categoria_inferida=False, itens=lista)
            for nome, lista in categorias.items()
        ],
    )
    revisao = [
        ItemParaRevisao(
            categoria=c.nome, indice_item=i, nome=item.nome, motivos=[MotivoRevisao.CONFIANCA_BAIXA]
        )
        for c in cardapio.categorias
        for i, item in enumerate(c.itens)
        if item.nome in em_revisao
    ]
    metricas = MetricasLLM(
        provedor="fake",
        modelo="fake",
        prompt_sha="0",
        tokens_entrada=1,
        tokens_saida=1,
        custo_estimado_usd=Decimal("0.01"),
        tempo_s=2.0,
        tentativas=1,
    )
    return ResultadoExtracao(cardapio=cardapio, revisao=revisao, metricas=metricas)


def _gabarito(*itens: ItemGabarito) -> Gabarito:
    return Gabarito("teste", "exato", "x.jpg", "própria", "teste", list(itens))


@pytest.mark.parametrize(
    ("a", "b", "minimo"),
    [
        ("X-Búrguer", "x burguer", 1.0),
        ("Nems", "Nems porc ou poulet", 0.85),
        ("Spanish Spinch", "Spanish Spinach", 0.8),
    ],
)
def test_similaridade_tolera_pequenas_diferencas(a: str, b: str, minimo: float) -> None:
    assert similaridade(a, b) >= minimo


def test_similaridade_baixa_para_itens_diferentes() -> None:
    assert similaridade("Bacon", "Tuna & Mayo") < 0.8
    assert similaridade("Nem", "Nems porc") < 0.85  # prefixo só vale para palavras inteiras


def test_casar_cada_item_uma_vez_pelos_mais_parecidos() -> None:
    esperados = [_esperado("Bacon"), _esperado("Bacon & Egg")]
    obtidos = [_obtido("Bacon & Egg"), _obtido("Bacon")]
    assert casar(esperados, obtidos) == [(0, 1), (1, 0)]


def test_casar_usa_a_categoria_para_desempatar_nomes_repetidos() -> None:
    esperados = [
        _esperado("Bacon", categoria="Sandwiches"),
        _esperado("Bacon", categoria="Make Your Own"),
    ]
    obtidos = [_obtido("Bacon", "MAKE YOUR OWN"), _obtido("Bacon", "Sandwiches")]
    assert casar(esperados, obtidos) == [(0, 1), (1, 0)]


def test_casar_ignora_quem_nao_tem_par() -> None:
    assert casar([_esperado("Bacon")], [_obtido("Suco de laranja")]) == []


def test_comparar_conta_recall_precisao_e_preco() -> None:
    gabarito = _gabarito(
        _esperado("X-Tudo", "20.00"), _esperado("Misto", "12.00"), _esperado("Suco")
    )
    resultado = _resultado(
        [
            ("Lanches", _extraido("X-Tudo", "20.00")),
            ("Lanches", _extraido("Misto", "13.00")),
            ("Lanches", _extraido("Pastel")),
        ]
    )
    contagem, problemas = comparar(gabarito, resultado)

    assert (contagem.esperados, contagem.extraidos, contagem.casados) == (3, 3, 2)
    assert (contagem.precos_avaliados, contagem.precos_corretos) == (2, 1)
    assert contagem.erros_sem_aviso == 1
    assert problemas == ["Misto: esperado 12,00, extraído 13,00 (sem aviso)"]


def test_erro_com_aviso_nao_conta_como_silencioso() -> None:
    gabarito = _gabarito(_esperado("Misto", "12.00"))
    resultado = _resultado([("Lanches", _extraido("Misto", "13.00"))], em_revisao=("Misto",))
    contagem, problemas = comparar(gabarito, resultado)

    assert (contagem.precos_corretos, contagem.erros_sem_aviso, contagem.em_revisao) == (0, 0, 1)
    assert problemas == ["Misto: esperado 12,00, extraído 13,00 (com aviso)"]


def test_variacoes_comparadas_pelos_precos() -> None:
    gabarito = _gabarito(_esperado("Pizza", None, variacoes=("32.00", "58.00")))
    certo = _resultado([("Pizzas", _extraido("Pizza", None, variacoes=("58.00", "32.00")))])
    errado = _resultado([("Pizzas", _extraido("Pizza", None, variacoes=("32.00", "55.00")))])
    assert comparar(gabarito, certo)[0].precos_corretos == 1
    assert comparar(gabarito, errado)[0].precos_corretos == 0


def test_mesmos_precos_organizados_de_outro_jeito_estao_certos() -> None:
    gabarito = _gabarito(_esperado("Bubble & Squeak", "3.80", variacoes=("1.90",)))
    como_item = _resultado([("Make", _extraido("Bubble & Squeak", "3.80", variacoes=("1.90",)))])
    como_variacoes = _resultado(
        [("Make", _extraido("Bubble & Squeak", None, variacoes=("3.80", "1.90")))]
    )
    assert comparar(gabarito, como_item)[0].precos_corretos == 1
    assert comparar(gabarito, como_variacoes)[0].precos_corretos == 1


def test_preco_a_mais_ou_a_menos_esta_errado() -> None:
    gabarito = _gabarito(_esperado("Bubble & Squeak", "3.80"))
    a_mais = _resultado([("Make", _extraido("Bubble & Squeak", "3.80", variacoes=("1.90",)))])
    a_menos = _resultado([("Make", _extraido("Bubble & Squeak", None))])
    assert comparar(gabarito, a_mais)[0].precos_corretos == 0
    assert comparar(gabarito, a_menos)[0].precos_corretos == 0


@pytest.mark.parametrize(
    ("preco", "em_revisao", "sem_aviso"),
    [(None, (), 0), ("3.80", (), 1), ("3.80", ("Bacon",), 0)],
)
def test_item_ilegivel(preco: str | None, em_revisao: tuple[str, ...], sem_aviso: int) -> None:
    gabarito = _gabarito(_esperado("Bacon", ilegivel=True, preco=None))
    contagem, _ = comparar(
        gabarito, _resultado([("Toasted", _extraido("Bacon", preco))], em_revisao)
    )

    assert (contagem.ilegiveis, contagem.ilegiveis_com_preco_sem_aviso) == (1, sem_aviso)
    assert contagem.precos_avaliados == 0  # ilegível não entra na acurácia de preço


def test_foto_sem_cardapio_tem_precisao_zero_se_inventar() -> None:
    contagem, _ = comparar(_gabarito(), _resultado([("Pratos", _extraido("Inventado"))]))
    assert (contagem.recall, contagem.precisao) == (None, 0.0)


def test_contagens_somam_e_as_taxas_saem_do_total() -> None:
    total = Contagem(esperados=10, casados=9, extraidos=9) + Contagem(
        esperados=10, casados=5, extraidos=10
    )
    assert total.recall == 14 / 20
    assert total.precisao == 14 / 19


def test_gabaritos_do_repositorio_carregam() -> None:
    gabaritos = run_evals.carregar_gabaritos()
    nomes = {g.cardapio for g in gabaritos}
    assert {"simulado_01", "belchers", "tivoli", "fachada", "salao"} <= nomes
    simulado = next(g for g in gabaritos if g.cardapio == "simulado_01")
    assert sum(item.ilegivel for item in simulado.itens) == 2
    for caminho in run_evals.DIR_GABARITOS.glob("*.json"):
        assert carregar_gabarito(caminho).licenca


def _resposta_do_simulado() -> str:
    """Acerta tudo menos o X-Tudo, inventa o preço ilegível do X-Frango e esquece a Água."""
    gabarito = run_evals.carregar_gabaritos(["simulado_01"])[0]
    categorias: dict[str, list[dict[str, Any]]] = {}
    for item in gabarito.itens:
        if item.nome == "Água com gás":
            continue
        preco: Decimal | None = item.preco
        if item.nome == "X-Tudo":
            preco = Decimal("99.00")
        if item.nome == "X-Frango":
            preco = Decimal("24.00")
        categorias.setdefault(item.categoria, []).append(
            {
                "nome": item.nome,
                "descricao_original": None,
                "preco": float(preco) if preco is not None else None,
                "variacoes": [
                    {"nome": f"V{n}", "preco": float(v)} for n, v in enumerate(item.variacoes) if v
                ],
                "adicionais": [],
                "alergenicos_provaveis": [],
                "confianca": 0.95,
                "observacao": None,
            }
        )
    return json.dumps(
        {
            "info_restaurante": {"nome": None, "telefone": None, "horario": None},
            "categorias": [
                {"nome": nome, "categoria_inferida": False, "itens": itens}
                for nome, itens in categorias.items()
            ],
        }
    )


def test_execucao_completa_sem_rede(config: Config, tmp_path: Path) -> None:
    resposta = _resposta_do_simulado()

    def criar(modelo: str) -> ProvedorFake:
        def responder(_midias: list[Midia] | Any) -> str:
            return resposta

        return ProvedorFake(modelo=modelo, responder=responder)

    gabaritos = run_evals.carregar_gabaritos(["simulado_01"])
    pasta = run_evals.executar(
        ["fake-a", "fake-b"], 2, gabaritos, criar, config, pasta=tmp_path / "execucao"
    )
    relatorio = run_evals.escrever_relatorio(pasta)

    assert sorted(p.name for p in (pasta / "fake-a").iterdir()) == [
        "simulado_01_1.json",
        "simulado_01_2.json",
    ]
    linha = next(linha for linha in relatorio.splitlines() if linha.startswith("| fake-a "))
    # 10 de 11 itens; preços legíveis: 8 de 9 certos (X-Tudo errado); X-Frango ilegível com preço
    assert "| 90,9% (20/22) |" in linha
    assert "| 88,9% (16/18) |" in linha
    assert "| 2 |" in linha  # X-Tudo errado sem aviso, nas 2 execuções
    assert "| 2 de 2 |" in linha  # X-Frango (a Água foi esquecida)
    assert "| 0/2 |" in linha
    assert "| simulado_01 | exato | 11 | 88,9% (88,9%–88,9%) | 88,9% (88,9%–88,9%) |" in relatorio
    detalhes = (pasta / "detalhes.md").read_text(encoding="utf-8")
    assert "X-Tudo: esperado 27,90, extraído 99,00 (sem aviso)" in detalhes
    assert "X-Frango: ilegível, extraído 24,00 sem aviso" in detalhes


def test_falha_do_provedor_entra_no_relatorio(config: Config, tmp_path: Path) -> None:
    gabaritos = run_evals.carregar_gabaritos(["simulado_01"])
    pasta = run_evals.executar(
        ["fake"],
        1,
        gabaritos,
        lambda modelo: ProvedorFake(modelo=modelo),
        config,
        pasta=tmp_path / "e",
    )
    relatorio = run_evals.escrever_relatorio(pasta)
    assert "| 1/1 |" in relatorio
    assert "falhou 1x" in relatorio


def test_reavaliar_nao_chama_o_modelo(config: Config, tmp_path: Path) -> None:
    resposta = _resposta_do_simulado()
    gabaritos = run_evals.carregar_gabaritos(["simulado_01"])
    pasta = run_evals.executar(
        ["fake"],
        1,
        gabaritos,
        lambda m: ProvedorFake([resposta], modelo=m),
        config,
        pasta=tmp_path / "e",
    )
    assert not (pasta / "relatorio.md").exists()
    assert run_evals.main(["--reavaliar", str(pasta)]) == 0
    assert (pasta / "relatorio.md").exists()


def test_retomar_refaz_so_o_que_falhou(config: Config, tmp_path: Path) -> None:
    resposta = _resposta_do_simulado()
    gabaritos = run_evals.carregar_gabaritos(["simulado_01"])
    pasta = tmp_path / "e"
    run_evals.executar(
        ["fake"], 2, gabaritos, lambda m: ProvedorFake(modelo=m), config, pasta=pasta
    )
    assert "| 2/2 |" in run_evals.escrever_relatorio(pasta)

    provedor = ProvedorFake([resposta, resposta], modelo="fake")
    run_evals.executar(["fake"], 2, gabaritos, lambda _m: provedor, config, pasta=pasta)
    assert len(provedor.chamadas) == 2
    assert "| 0/2 |" in run_evals.escrever_relatorio(pasta)

    outra_vez = ProvedorFake(modelo="fake")
    run_evals.executar(["fake"], 2, gabaritos, lambda _m: outra_vez, config, pasta=pasta)
    assert outra_vez.chamadas == []  # o que já deu certo não é repetido
