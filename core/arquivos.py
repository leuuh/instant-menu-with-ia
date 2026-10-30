"""Validação e preparo dos arquivos enviados (imagem ou PDF) antes de ir ao LLM."""

import io
from pathlib import Path

from PIL import Image, ImageOps

from core.providers.base import Midia

FORMATOS_ACEITOS = {"JPEG", "PNG"}
QUALIDADE_JPEG = 90
ASSINATURA_PDF = b"%PDF-"
MAX_BYTES_PDF = 50 * 1024 * 1024  # limite do Gemini para PDF


class ArquivoInvalidoErro(ValueError):
    """Arquivo ausente, corrompido ou em formato não aceito."""


def carregar_arquivo(caminho: Path, max_lado: int) -> Midia:
    """Lê o arquivo do disco e o prepara para envio."""
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise ArquivoInvalidoErro(f"Arquivo não encontrado ou inacessível: {caminho}") from erro
    return preparar_arquivo(dados, caminho.name, max_lado)


def preparar_arquivo(dados: bytes, nome: str, max_lado: int) -> Midia:
    """Identifica o tipo pelo conteúdo, não pela extensão, e prepara imagem ou PDF."""
    if dados.startswith(ASSINATURA_PDF):
        return _preparar_pdf(dados, nome)
    return _preparar_imagem(dados, nome, max_lado)


def _preparar_pdf(dados: bytes, nome: str) -> Midia:
    if len(dados) > MAX_BYTES_PDF:
        limite_mb = MAX_BYTES_PDF // (1024 * 1024)
        raise ArquivoInvalidoErro(f"{nome}: o PDF passa do limite de {limite_mb} MB.")
    return Midia(dados=dados, mime="application/pdf")


def _preparar_imagem(dados: bytes, nome: str, max_lado: int) -> Midia:
    """Valida JPG/PNG, corrige rotação EXIF, reduz e regrava como JPEG."""
    try:
        with Image.open(io.BytesIO(dados)) as original:
            if original.format not in FORMATOS_ACEITOS:
                raise ArquivoInvalidoErro(
                    f"{nome}: formato {original.format} não aceito (use JPG, PNG ou PDF)."
                )
            imagem = _para_rgb(ImageOps.exif_transpose(original))
            imagem.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)
            return Midia(dados=_para_jpeg(imagem), mime="image/jpeg")
    except (OSError, SyntaxError, Image.DecompressionBombError) as erro:
        raise ArquivoInvalidoErro(f"{nome} não é uma imagem válida.") from erro


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
