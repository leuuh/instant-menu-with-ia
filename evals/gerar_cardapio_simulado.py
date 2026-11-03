"""Gera uma foto simulada de cardápio fictício e o gabarito correspondente.

A imagem é desenhada, não fotografada: como o texto é conhecido, dá para conferir a extração
item a item. Simula problemas comuns de foto (inclinação, sombra, reflexo, desfoque, ruído e
rotação EXIF) e três armadilhas de preço: um coberto por mancha, um cortado por dobra no papel e
um riscado com o novo preço escrito à mão. Não substitui fotos reais nos evals.

Uso (Windows, por causa das fontes): python evals/gerar_cardapio_simulado.py
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

DIR_SAIDA = Path(__file__).parent / "data"
NOME_BASE = "cardapio_simulado_01"

LARGURA_PAPEL = 1250
MARGEM_MESA = 200
ORIENTACAO_EXIF = 0x0112
ROTACAO_90_HORARIO = 6

TINTA = (40, 32, 28)
TINTA_CANETA = (25, 45, 140)
COR_PAPEL = (246, 238, 220)
COR_VERSO = (222, 212, 192)
COR_MANCHA = (112, 74, 38)
COR_MESA = (92, 62, 42)

Fonte = ImageFont.FreeTypeFont
Caixa = tuple[float, float, float, float]


@dataclass(frozen=True)
class Item:
    nome: str
    preco: str | None = None
    descricao: str | None = None
    variacoes: tuple[tuple[str, str], ...] = ()
    preco_riscado: str | None = None
    obstaculo: Literal["mancha", "dobra"] | None = None


@dataclass(frozen=True)
class Categoria:
    nome: str
    itens: tuple[Item, ...]
    nota: str | None = None
    adicionais: tuple[tuple[str, str], ...] = ()


INFO = {
    "nome": "Recanto Fictício",
    "telefone": "(11) 4000-0000",
    "horario": "Ter. a dom., das 18h às 23h",
}
SLOGAN = "O sabor que você imagina!"
ENDERECO = "Rua Imaginária, 123 · Tel. (11) 4000-0000 · Ter. a dom., das 18h às 23h"

COLUNA_ESQUERDA = (
    Categoria(
        "ENTRADAS",
        (
            Item("Porção de batata frita", variacoes=(("P", "18,00"), ("G", "29,90"))),
            Item("Bolinho de bacalhau (6 un.)", "34,50", "Com maionese de ervas"),
            Item("Pastel de queijo", "9,50", preco_riscado="8,00"),
        ),
    ),
    Categoria(
        "LANCHES",
        (
            Item("X-Tudo", "27,90", "Pão, hambúrguer, ovo, bacon, queijo e salada"),
            Item("X-Frango", "24,00", "Pão, frango desfiado e requeijão", obstaculo="mancha"),
            Item("Misto quente", "12,00"),
        ),
        nota="Adicionais: bacon R$ 4,00 · ovo R$ 2,50",
        adicionais=(("bacon", "4,00"), ("ovo", "2,50")),
    ),
)
COLUNA_DIREITA = (
    Categoria(
        "PIZZAS",
        (
            Item(
                "Portuguesa",
                descricao="Presunto, ovo, cebola e azeitona",
                variacoes=(("Meia", "32,00"), ("Inteira", "58,00")),
            ),
            Item(
                "Quatro queijos",
                descricao="Mussarela, provolone, parmesão e gorgonzola",
                variacoes=(("Meia", "34,00"), ("Inteira", "62,00")),
            ),
        ),
        nota="Borda recheada + R$ 8,00",
        adicionais=(("Borda recheada", "8,00"),),
    ),
    Categoria(
        "BEBIDAS",
        (
            Item("Refrigerante lata", "6,50"),
            Item("Suco natural", variacoes=(("300ml", "9,00"), ("500ml", "14,00"))),
            Item("Água com gás", "4,50", obstaculo="dobra"),
        ),
    ),
)


def _fonte(arquivo: str, tamanho: int) -> Fonte:
    return ImageFont.truetype(arquivo, tamanho)


def _quebrar_linhas(texto: str, fonte: Fonte, largura: float) -> list[str]:
    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if fonte.getlength(tentativa) <= largura:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    return [*linhas, atual]


def _desenhar_pontos(desenho: ImageDraw.ImageDraw, inicio: float, fim: float, y: int) -> None:
    fonte = _fonte("georgia.ttf", 24)
    x = inicio + 10
    while x < fim - 14:
        desenho.text((x, y + 4), ".", font=fonte, fill=TINTA)
        x += 12


def _desenhar_preco_riscado(
    desenho: ImageDraw.ImageDraw, item: Item, direita: float, y: int
) -> float:
    """Preço antigo riscado à caneta com o novo escrito à mão; devolve o x onde começa."""
    fonte = _fonte("georgia.ttf", 28)
    antigo = f"R$ {item.preco_riscado}"
    x_antigo = direita - fonte.getlength(antigo)
    desenho.text((x_antigo, y), antigo, font=fonte, fill=TINTA)
    desenho.line((x_antigo - 4, y + 18, direita + 4, y + 16), fill=TINTA_CANETA, width=4)
    fonte_mao = _fonte("segoepr.ttf", 32)
    novo = f"R$ {item.preco}"
    x_novo = x_antigo - fonte_mao.getlength(novo) - 16
    desenho.text((x_novo, y - 8), novo, font=fonte_mao, fill=TINTA_CANETA)
    return x_novo


def _desenhar_item(
    desenho: ImageDraw.ImageDraw, item: Item, x: int, largura: int, y: int
) -> tuple[int, Caixa | None]:
    """Desenha o item; devolve o novo y e a caixa do preço (para mancha ou dobra)."""
    fonte_nome = _fonte("georgiab.ttf", 28)
    fonte_preco = _fonte("georgia.ttf", 28)
    direita = x + largura
    caixa: Caixa | None = None
    desenho.text((x, y), item.nome, font=fonte_nome, fill=TINTA)
    fim_nome = x + fonte_nome.getlength(item.nome)
    if item.preco_riscado:
        inicio = _desenhar_preco_riscado(desenho, item, direita, y)
        _desenhar_pontos(desenho, fim_nome, inicio, y)
    elif item.preco:
        texto = f"R$ {item.preco}"
        inicio = direita - fonte_preco.getlength(texto)
        desenho.text((inicio, y), texto, font=fonte_preco, fill=TINTA)
        _desenhar_pontos(desenho, fim_nome, inicio, y)
        caixa = (inicio, y, direita, y + 34)
    y += 40
    if item.descricao:
        fonte_descricao = _fonte("georgiai.ttf", 23)
        for linha in _quebrar_linhas(item.descricao, fonte_descricao, largura - 20):
            desenho.text((x, y), linha, font=fonte_descricao, fill=TINTA)
            y += 30
    if item.variacoes:
        texto = "   ".join(f"{nome} R$ {preco}" for nome, preco in item.variacoes)
        desenho.text((x + 20, y), texto, font=fonte_preco, fill=TINTA)
        y += 40
    return y + 14, caixa


def _desenhar_coluna(
    desenho: ImageDraw.ImageDraw, categorias: tuple[Categoria, ...], x: int, y: int, largura: int
) -> tuple[int, dict[str, Caixa]]:
    obstaculos: dict[str, Caixa] = {}
    for categoria in categorias:
        desenho.text((x, y), categoria.nome, font=_fonte("georgiab.ttf", 38), fill=TINTA)
        y += 50
        desenho.line((x, y, x + largura, y), fill=TINTA, width=2)
        y += 14
        for item in categoria.itens:
            y, caixa = _desenhar_item(desenho, item, x, largura, y)
            if item.obstaculo and caixa:
                obstaculos[item.obstaculo] = caixa
        if categoria.nota:
            desenho.text((x, y), categoria.nota, font=_fonte("georgiai.ttf", 25), fill=TINTA)
            y += 44
        y += 34
    return y, obstaculos


def _centralizar(
    desenho: ImageDraw.ImageDraw, texto: str, y: int, fonte: Fonte, largura: int
) -> None:
    desenho.text(((largura - fonte.getlength(texto)) / 2, y), texto, font=fonte, fill=TINTA)


def _desenhar_cabecalho(desenho: ImageDraw.ImageDraw, largura: int) -> int:
    _centralizar(desenho, INFO["nome"], 50, _fonte("georgiab.ttf", 78), largura)
    _centralizar(desenho, SLOGAN, 148, _fonte("georgiai.ttf", 32), largura)
    _centralizar(desenho, ENDERECO, 196, _fonte("georgia.ttf", 23), largura)
    desenho.line((70, 240, largura - 70, 240), fill=TINTA, width=3)
    return 275


def _textura(tamanho: tuple[int, int], cor: tuple[int, int, int], sigma: float) -> Image.Image:
    base = Image.new("RGB", tamanho, cor)
    ruido = Image.effect_noise(tamanho, sigma).convert("RGB")
    return ImageChops.overlay(base, ruido)


def _aplicar_mancha(papel: Image.Image, caixa: Caixa) -> None:
    """Mancha opaca sobre o preço, com bordas suaves: os dígitos ficam realmente ilegíveis."""
    camada = Image.new("L", papel.size, 0)
    desenho = ImageDraw.Draw(camada)
    x0, y0, x1, y1 = caixa
    desenho.ellipse((x0 + 30, y0 - 44, x1 - 6, y0 + 10), fill=235)
    desenho.ellipse((x0 - 40, y1 - 12, x0 + 44, y1 + 34), fill=225)
    desenho.ellipse((x0 - 22, y0 - 26, x1 + 22, y1 + 26), fill=255)  # por último: cobre tudo
    camada = camada.filter(ImageFilter.GaussianBlur(3))
    papel.paste(Image.new("RGB", papel.size, COR_MANCHA), mask=camada)


def _aplicar_dobra(papel: Image.Image, caixa: Caixa) -> None:
    """Canto do papel dobrado sobre o preço: só o 'R$' fica visível, o valor fica coberto."""
    largura, altura = papel.size
    x0, y0, x1, y1 = caixa
    k = (x0 + x1) / 2 + (y0 + y1) / 2
    triangulo = [(largura, k - largura), (k - altura, altura), (largura, altura)]
    sombra = Image.new("L", papel.size, 0)
    ImageDraw.Draw(sombra).polygon(triangulo, fill=110)
    sombra = sombra.filter(ImageFilter.GaussianBlur(10))
    papel.paste(Image.new("RGB", papel.size, (60, 50, 40)), mask=sombra)
    ImageDraw.Draw(papel).polygon(triangulo, fill=COR_VERSO)


def desenhar_papel() -> Image.Image:
    """Cardápio plano: texto, colunas e as armadilhas de preço."""
    rascunho = Image.new("RGB", (LARGURA_PAPEL, 2400), COR_PAPEL)
    desenho = ImageDraw.Draw(rascunho)
    y = _desenhar_cabecalho(desenho, LARGURA_PAPEL)
    fim_esquerda, obstaculos = _desenhar_coluna(desenho, COLUNA_ESQUERDA, 70, y, 520)
    fim_direita, outros = _desenhar_coluna(desenho, COLUNA_DIREITA, 660, y, 520)
    obstaculos.update(outros)
    altura = max(fim_esquerda, fim_direita) + 10
    papel = ImageChops.multiply(
        rascunho.crop((0, 0, LARGURA_PAPEL, altura)),
        _textura((LARGURA_PAPEL, altura), (250, 250, 250), 14),
    )
    _aplicar_mancha(papel, obstaculos["mancha"])
    _aplicar_dobra(papel, obstaculos["dobra"])
    return papel


def _sobre_mesa(papel: Image.Image) -> Image.Image:
    """Coloca o papel inclinado sobre uma mesa, com sombra projetada."""
    tamanho = (papel.width + 2 * MARGEM_MESA, papel.height + 2 * MARGEM_MESA)
    veios = Image.effect_noise((tamanho[0], 60), 50).resize(tamanho).convert("RGB")
    cena = ImageChops.overlay(Image.new("RGB", tamanho, COR_MESA), veios)
    girado = papel.convert("RGBA").rotate(-2.5, expand=True, resample=Image.Resampling.BICUBIC)
    posicao = ((tamanho[0] - girado.width) // 2, (tamanho[1] - girado.height) // 2)
    alfa = girado.getchannel("A")
    sombra = Image.new("L", tamanho, 0)
    sombra.paste(alfa.point(lambda v: v // 2), (posicao[0] + 14, posicao[1] + 18))
    cena.paste((0, 0, 0), mask=sombra.filter(ImageFilter.GaussianBlur(16)))
    cena.paste(girado, posicao, alfa)
    return cena


def _efeitos_de_camera(cena: Image.Image) -> Image.Image:
    """Perspectiva, sombra lateral, reflexo, desfoque e ruído."""
    largura, altura = cena.size
    quadro = (110, 50, 20, altura - 15, largura - 30, altura - 10, largura - 90, 25)
    cena = cena.transform(
        cena.size, Image.Transform.QUAD, quadro, resample=Image.Resampling.BICUBIC
    )
    degrade = (
        Image.linear_gradient("L").rotate(90).resize(cena.size).point(lambda v: 150 + v // 2.6)
    )
    cena = ImageChops.multiply(cena, degrade.convert("RGB"))
    reflexo = Image.new("L", cena.size, 0)
    ImageDraw.Draw(reflexo).ellipse(
        (int(largura * 0.52), int(altura * 0.2), int(largura * 0.92), int(altura * 0.42)), fill=120
    )
    reflexo = reflexo.filter(ImageFilter.GaussianBlur(90))
    cena.paste((255, 255, 250), mask=reflexo)
    cena = cena.filter(ImageFilter.GaussianBlur(0.9))
    return Image.blend(cena, Image.effect_noise(cena.size, 40).convert("RGB"), 0.05)


def _item_gabarito(item: Item, categoria: Categoria) -> dict[str, Any]:
    return {
        "categoria": categoria.nome,
        "nome": item.nome,
        "preco": None if item.obstaculo else _numero(item.preco),
        "variacoes": [{"nome": n, "preco": _numero(p)} for n, p in item.variacoes],
        "ilegivel": item.obstaculo is not None,
    }


def _numero(preco: str | None) -> float | None:
    return float(preco.replace(",", ".")) if preco else None


def gabarito() -> dict[str, Any]:
    """O que deve ser extraído. Preço coberto por mancha ou dobra é ilegível: o certo é null."""
    categorias = [*COLUNA_ESQUERDA, *COLUNA_DIREITA]
    return {
        "cardapio": "simulado_01",
        "tipo": "exato",
        "arquivo": f"evals/data/{NOME_BASE}.jpg",
        "licenca": "própria",
        "conferencia": (
            "Gabarito exato: a imagem foi desenhada a partir dele "
            "(evals/gerar_cardapio_simulado.py)."
        ),
        "itens": [_item_gabarito(i, c) for c in categorias for i in c.itens],
    }


def main() -> None:
    DIR_SAIDA.mkdir(parents=True, exist_ok=True)
    foto = _efeitos_de_camera(_sobre_mesa(desenhar_papel()))
    exif = Image.Exif()
    exif[ORIENTACAO_EXIF] = ROTACAO_90_HORARIO
    foto.transpose(Image.Transpose.ROTATE_90).save(
        DIR_SAIDA / f"{NOME_BASE}.jpg", quality=78, exif=exif
    )
    destino = DIR_SAIDA / "gabaritos" / "simulado_01.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(gabarito(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
