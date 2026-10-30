import io
from pathlib import Path

import pytest
from PIL import Image

from core.imagens import ImagemInvalidaErro, carregar_imagem

ORIENTACAO_EXIF = 0x0112
ROTACAO_90_HORARIO = 6


def _abrir(dados: bytes) -> Image.Image:
    return Image.open(io.BytesIO(dados))


def test_reduz_lado_maior_e_converte_para_jpeg(tmp_path: Path) -> None:
    caminho = tmp_path / "grande.png"
    Image.new("RGB", (4000, 1000), "white").save(caminho)
    midia = carregar_imagem(caminho, max_lado=2000)
    assert midia.mime == "image/jpeg"
    assert _abrir(midia.dados).size == (2000, 500)


def test_nao_aumenta_imagem_pequena(tmp_path: Path) -> None:
    caminho = tmp_path / "pequena.jpg"
    Image.new("RGB", (800, 600), "white").save(caminho)
    assert _abrir(carregar_imagem(caminho, max_lado=3072).dados).size == (800, 600)


def test_aplica_rotacao_exif(tmp_path: Path) -> None:
    caminho = tmp_path / "girada.jpg"
    exif = Image.Exif()
    exif[ORIENTACAO_EXIF] = ROTACAO_90_HORARIO
    Image.new("RGB", (400, 200), "white").save(caminho, exif=exif)
    assert _abrir(carregar_imagem(caminho, max_lado=3072).dados).size == (200, 400)


def test_transparencia_vira_fundo_branco(tmp_path: Path) -> None:
    caminho = tmp_path / "transparente.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(caminho)
    pixel = _abrir(carregar_imagem(caminho, max_lado=3072).dados).getpixel((5, 5))
    assert isinstance(pixel, tuple)
    assert min(pixel) > 240


def test_rejeita_arquivo_que_nao_e_imagem(tmp_path: Path) -> None:
    caminho = tmp_path / "falso.jpg"
    caminho.write_text("isto não é uma imagem", encoding="utf-8")
    with pytest.raises(ImagemInvalidaErro):
        carregar_imagem(caminho, max_lado=3072)


def test_rejeita_formato_nao_aceito(tmp_path: Path) -> None:
    caminho = tmp_path / "imagem.gif"
    Image.new("RGB", (10, 10)).save(caminho)
    with pytest.raises(ImagemInvalidaErro, match="GIF"):
        carregar_imagem(caminho, max_lado=3072)


def test_rejeita_arquivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ImagemInvalidaErro, match="não encontrado"):
        carregar_imagem(tmp_path / "nao_existe.jpg", max_lado=3072)
