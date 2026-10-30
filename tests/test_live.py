"""Teste com a API real. Rode com: python -m pytest -m live (gera custo)."""

from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from core.config import Config
from core.enrich import ItemParaDescrever, gerar_descricoes
from core.extract import extrair_arquivos, extrair_cardapio
from core.providers import criar_provedor

LINHAS_CARDAPIO = [
    ("LANCHES", None),
    ("X-Burguer ............ R$ 22,90", Decimal("22.90")),
    ("X-Salada ............. R$ 24,50", Decimal("24.50")),
    ("BEBIDAS", None),
    ("Suco de laranja 300ml .. R$ 9,00", Decimal("9.00")),
]

pytestmark = pytest.mark.live


def _desenhar_cardapio(caminho: Path) -> None:
    imagem = Image.new("RGB", (900, 500), "white")
    desenho = ImageDraw.Draw(imagem)
    fonte = ImageFont.load_default(size=36)
    for indice, (texto, _) in enumerate(LINHAS_CARDAPIO):
        desenho.text((40, 40 + indice * 85), texto, fill="black", font=fonte)
    imagem.save(caminho)


def test_extrai_precos_de_pdf(tmp_path: Path) -> None:
    config = Config(dir_logs=tmp_path / "logs")
    if config.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY não definida no .env")
    imagem = tmp_path / "cardapio.png"
    _desenhar_cardapio(imagem)
    pdf = tmp_path / "cardapio_ficticio.pdf"
    Image.open(imagem).save(pdf)

    resultado = extrair_cardapio(pdf, criar_provedor(config), config)

    precos = {item.preco for categoria in resultado.cardapio.categorias for item in categoria.itens}
    assert {preco for _, preco in LINHAS_CARDAPIO if preco is not None} <= precos


def test_extrai_precos_de_cardapio_ficticio(tmp_path: Path) -> None:
    config = Config(dir_logs=tmp_path / "logs")
    if config.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY não definida no .env")
    caminho = tmp_path / "cardapio_ficticio.png"
    _desenhar_cardapio(caminho)

    resultado = extrair_cardapio(caminho, criar_provedor(config), config)

    precos = {item.preco for categoria in resultado.cardapio.categorias for item in categoria.itens}
    esperados = {preco for _, preco in LINHAS_CARDAPIO if preco is not None}
    assert esperados <= precos
    assert resultado.metricas.custo_estimado_usd is not None


def test_duas_fotos_sobrepostas_sem_item_repetido(tmp_path: Path) -> None:
    config = Config(dir_logs=tmp_path / "logs")
    if config.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY não definida no .env")
    inteira = tmp_path / "cardapio.png"
    _desenhar_cardapio(inteira)
    imagem = Image.open(inteira)
    cima, baixo = tmp_path / "cima.png", tmp_path / "baixo.png"
    imagem.crop((0, 0, imagem.width, 300)).save(cima)  # as duas fotos mostram o X-Salada
    imagem.crop((0, 140, imagem.width, imagem.height)).save(baixo)

    resultado = extrair_arquivos([cima, baixo], criar_provedor(config), config)

    nomes = [i.nome for c in resultado.cardapio.categorias for i in c.itens]
    assert len([nome for nome in nomes if "salada" in nome.lower()]) == 1
    assert resultado.cardapio.total_itens() == 3
    assert len(resultado.metricas.arquivos) == 2


def test_descricoes_sugeridas_com_a_api_real(tmp_path: Path) -> None:
    config = Config(dir_logs=tmp_path / "logs")
    if config.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY não definida no .env")
    itens = [
        ItemParaDescrever(0, "Lanches", "X-Frango", "Pão, frango desfiado e requeijão"),
        ItemParaDescrever(1, "Bebidas", "Suco de laranja"),
    ]

    resultado = gerar_descricoes(itens, criar_provedor(config), config)

    assert len(resultado.sugestoes) + len(resultado.descartadas) == 2
    assert resultado.metricas.custo_estimado_usd is not None
