import io
from pathlib import Path

import pytest
from PIL import Image

from core.arquivos import (
    MAX_BYTES_PDF,
    MAX_IMAGENS,
    ArquivoInvalidoErro,
    carregar_arquivo,
    preparar_arquivo,
    preparar_arquivos,
)

ORIENTACAO_EXIF = 0x0112
ROTACAO_90_HORARIO = 6
MAX_LADO = 3072


def _abrir(dados: bytes) -> Image.Image:
    return Image.open(io.BytesIO(dados))


def _bytes_imagem(
    tamanho: tuple[int, int] = (800, 600), formato: str = "PNG", **opcoes: object
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", tamanho, "white").save(buffer, format=formato, **opcoes)
    return buffer.getvalue()


def test_reduz_lado_maior_e_converte_para_jpeg() -> None:
    midia = preparar_arquivo(_bytes_imagem((4000, 1000)), "grande.png", max_lado=2000)
    assert midia.mime == "image/jpeg"
    assert _abrir(midia.dados).size == (2000, 500)


def test_nao_aumenta_imagem_pequena() -> None:
    midia = preparar_arquivo(_bytes_imagem((800, 600), "JPEG"), "pequena.jpg", MAX_LADO)
    assert _abrir(midia.dados).size == (800, 600)


def test_aplica_rotacao_exif() -> None:
    exif = Image.Exif()
    exif[ORIENTACAO_EXIF] = ROTACAO_90_HORARIO
    dados = _bytes_imagem((400, 200), "JPEG", exif=exif)
    assert _abrir(preparar_arquivo(dados, "girada.jpg", MAX_LADO).dados).size == (200, 400)


def test_transparencia_vira_fundo_branco() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, format="PNG")
    midia = preparar_arquivo(buffer.getvalue(), "transparente.png", MAX_LADO)
    pixel = _abrir(midia.dados).getpixel((5, 5))
    assert isinstance(pixel, tuple)
    assert min(pixel) > 240


def test_tipo_vem_do_conteudo_e_nao_da_extensao() -> None:
    midia = preparar_arquivo(_bytes_imagem(formato="PNG"), "enganoso.pdf", MAX_LADO)
    assert midia.mime == "image/jpeg"


def test_pdf_passa_sem_alteracao() -> None:
    dados = b"%PDF-1.7\nconteudo"
    midia = preparar_arquivo(dados, "cardapio.pdf", MAX_LADO)
    assert (midia.mime, midia.dados) == ("application/pdf", dados)


def test_rejeita_pdf_acima_do_limite() -> None:
    dados = b"%PDF-" + b"0" * MAX_BYTES_PDF
    with pytest.raises(ArquivoInvalidoErro, match="limite"):
        preparar_arquivo(dados, "enorme.pdf", MAX_LADO)


@pytest.mark.parametrize("dados", [b"isto nao e uma imagem", b""])
def test_rejeita_conteudo_que_nao_e_imagem(dados: bytes) -> None:
    with pytest.raises(ArquivoInvalidoErro, match="não é uma imagem válida"):
        preparar_arquivo(dados, "falso.jpg", MAX_LADO)


def test_rejeita_imagem_cortada() -> None:
    inteira = _bytes_imagem((800, 600), "JPEG")
    with pytest.raises(ArquivoInvalidoErro, match="não é uma imagem válida"):
        preparar_arquivo(inteira[: len(inteira) // 2], "cortada.jpg", MAX_LADO)


def test_rejeita_formato_nao_aceito() -> None:
    with pytest.raises(ArquivoInvalidoErro, match="GIF"):
        preparar_arquivo(_bytes_imagem(formato="GIF"), "imagem.gif", MAX_LADO)


def test_carrega_do_disco(tmp_path: Path) -> None:
    caminho = tmp_path / "foto.png"
    caminho.write_bytes(_bytes_imagem())
    assert carregar_arquivo(caminho, MAX_LADO).mime == "image/jpeg"


def test_rejeita_arquivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ArquivoInvalidoErro, match="não encontrado"):
        carregar_arquivo(tmp_path / "nao_existe.jpg", MAX_LADO)


def test_aceita_ate_cinco_imagens() -> None:
    arquivos = [(f"{n}.png", _bytes_imagem()) for n in range(MAX_IMAGENS)]
    entradas = preparar_arquivos(arquivos, MAX_LADO)
    assert [e.nome for e in entradas] == [f"{n}.png" for n in range(MAX_IMAGENS)]
    assert all(e.midia.mime == "image/jpeg" for e in entradas)


def test_recusa_mais_de_cinco_imagens() -> None:
    arquivos = [(f"{n}.png", b"nem_chega_a_abrir") for n in range(MAX_IMAGENS + 1)]
    with pytest.raises(ArquivoInvalidoErro, match="no máximo 5"):
        preparar_arquivos(arquivos, MAX_LADO)


def test_aceita_um_pdf_sozinho() -> None:
    entradas = preparar_arquivos([("menu.pdf", b"%PDF-1.7")], MAX_LADO)
    assert entradas[0].midia.mime == "application/pdf"


@pytest.mark.parametrize(
    "arquivos",
    [
        [("a.pdf", b"%PDF-1.7"), ("b.pdf", b"%PDF-1.7")],
        [("a.pdf", b"%PDF-1.7"), ("b.png", b"imagem")],
    ],
)
def test_recusa_mais_de_um_pdf_ou_mistura(arquivos: list[tuple[str, bytes]]) -> None:
    with pytest.raises(ArquivoInvalidoErro, match="sem misturar"):
        preparar_arquivos(arquivos, MAX_LADO)


def test_recusa_selecao_vazia() -> None:
    with pytest.raises(ArquivoInvalidoErro, match="pelo menos um"):
        preparar_arquivos([], MAX_LADO)


def test_um_arquivo_ruim_recusa_a_selecao_e_cita_o_nome() -> None:
    with pytest.raises(ArquivoInvalidoErro, match="ruim.jpg"):
        preparar_arquivos([("boa.png", _bytes_imagem()), ("ruim.jpg", b"texto")], MAX_LADO)
