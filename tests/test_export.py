import csv
import io
import json
from decimal import Decimal

from core.export import COLUNAS_CSV, exportar_csv, exportar_json
from core.revisao import itens_para_revisao
from core.schema import ExtracaoCardapio

LIMIAR = 0.7


def _cardapio(json_valido: str) -> ExtracaoCardapio:
    return ExtracaoCardapio.model_validate_json(json_valido)


def _linhas_csv(dados: bytes) -> list[dict[str, str]]:
    texto = dados.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texto, newline=""), delimiter=";"))


def _exportar_csv(json_valido: str) -> bytes:
    cardapio = _cardapio(json_valido)
    return exportar_csv(cardapio, itens_para_revisao(cardapio, LIMIAR))


def test_json_tem_o_contrato_e_as_pendencias(json_valido: str) -> None:
    cardapio = _cardapio(json_valido)
    dados = json.loads(exportar_json(cardapio, itens_para_revisao(cardapio, LIMIAR)))

    assert dados["info_restaurante"]["nome"] == "Lanchonete Sabor da Praça"
    assert dados["categorias"][0]["itens"][0]["preco"] == 32.9
    assert dados["categorias"][0]["itens"][1]["preco"] is None
    assert dados["pendencias_revisao"][0] == {
        "categoria": "Lanches",
        "indice_item": 1,
        "nome": "X-Salada",
        "motivos": ["confianca_baixa", "preco_ausente"],
    }


def test_json_mantem_acentos_legiveis(json_valido: str) -> None:
    assert "Praça".encode() in exportar_json(_cardapio(json_valido), [])


def test_csv_abre_no_excel_em_portugues(json_valido: str) -> None:
    dados = _exportar_csv(json_valido)
    assert dados.startswith(b"\xef\xbb\xbf")
    assert dados.decode("utf-8-sig").splitlines()[0] == ";".join(COLUNAS_CSV)


def test_csv_usa_virgula_decimal(json_valido: str) -> None:
    primeira = _linhas_csv(_exportar_csv(json_valido))[0]
    assert primeira["item"] == "X-Burguer"
    assert primeira["preco"] == "32,90"
    assert primeira["confianca"] == "0,95"
    assert primeira["adicionais"] == "Bacon: 4,00"
    assert primeira["alergenicos_provaveis"] == "glúten, lactose, ovo"
    assert primeira["pendente_revisao"] == "não"


def test_csv_tem_uma_linha_por_variacao(json_valido: str) -> None:
    linhas = [li for li in _linhas_csv(_exportar_csv(json_valido)) if li["item"] == "Calabresa"]
    assert [(li["opcao"], li["preco"]) for li in linhas] == [
        ("Média", "45,00"),
        ("Grande", "58,50"),
    ]


def test_csv_deixa_preco_desconhecido_vazio_nunca_zero(json_valido: str) -> None:
    linha = next(li for li in _linhas_csv(_exportar_csv(json_valido)) if li["item"] == "X-Salada")
    assert linha["preco"] == ""
    assert linha["pendente_revisao"] == "sim"
    assert linha["motivos_revisao"] == "leitura incerta, sem preço"


def test_csv_item_com_preco_e_variacoes_gera_as_duas_linhas(json_valido: str) -> None:
    cardapio = _cardapio(json_valido)
    calabresa = cardapio.categorias[1].itens[0]
    cardapio.categorias[1].itens[0] = calabresa.model_copy(update={"preco": Decimal("40.00")})
    linhas = [li for li in _linhas_csv(exportar_csv(cardapio, [])) if li["item"] == "Calabresa"]
    assert [li["opcao"] for li in linhas] == ["", "Média", "Grande"]


def test_csv_neutraliza_formulas(json_valido: str) -> None:
    cardapio = _cardapio(json_valido)
    item = cardapio.categorias[0].itens[0]
    cardapio.categorias[0].itens[0] = item.model_copy(
        update={"nome": "=HYPERLINK(1)", "descricao_original": "+ bacon", "observacao": "@soma"}
    )
    linha = _linhas_csv(exportar_csv(cardapio, []))[0]
    assert linha["item"] == "'=HYPERLINK(1)"
    assert linha["descricao"] == "'+ bacon"
    assert linha["observacao"] == "'@soma"


def test_csv_preserva_texto_com_ponto_e_virgula(json_valido: str) -> None:
    cardapio = _cardapio(json_valido)
    item = cardapio.categorias[0].itens[0]
    cardapio.categorias[0].itens[0] = item.model_copy(update={"descricao_original": "a; b"})
    assert _linhas_csv(exportar_csv(cardapio, []))[0]["descricao"] == "a; b"
