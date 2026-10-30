"""Leitura e preparo de imagens antes do envio ao LLM."""

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from core.providers.base import Midia

FORMATOS_ACEITOS = {"JPEG", "PNG"}
QUALIDADE_JPEG = 90


class ImagemInvalidaErro(ValueError):
    """Arquivo ausente, corrompido ou em formato não aceito."""


def carregar_imagem(caminho: Path, max_lado: int) -> Midia:
    """Valida JPG/PNG pelo conteúdo, corrige rotação EXIF, reduz e regrava como JPEG."""
    try:
        with Image.open(caminho) as original:
            if original.format not in FORMATOS_ACEITOS:
                raise ImagemInvalidaErro(
                    f"{caminho.name}: formato {original.format} não aceito (use JPG ou PNG)."
                )
            imagem = ImageOps.exif_transpose(original)
            imagem = _para_rgb(imagem)
            imagem.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)
            return Midia(dados=_para_jpeg(imagem), mime="image/jpeg")
    except FileNotFoundError as erro:
        raise ImagemInvalidaErro(f"Arquivo não encontrado: {caminho}") from erro
    except UnidentifiedImageError as erro:
        raise ImagemInvalidaErro(f"{caminho.name} não é uma imagem válida.") from erro


def _para_rgb(imagem: Image.Image) -> Image.Image:
    """Converte para RGB, trocando transparência por fundo branco."""
    tem_alfa = imagem.mode in ("RGBA", "LA") or (
        imagem.mode == "P" and "transparency" in imagem.info
    )
    if not tem_alfa:
        return imagem.convert("RGB")
    rgba = imagem.convert("RGBA")
    fundo = Image.new("RGB", rgba.size, "white")
    fundo.paste(rgba, mask=rgba.getchannel("A"))
    return fundo


def _para_jpeg(imagem: Image.Image) -> bytes:
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=QUALIDADE_JPEG)
    return buffer.getvalue()
