"""Contrato comum a todos os provedores de LLM."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

MimeMidia = Literal["image/jpeg", "image/png", "application/pdf"]


@dataclass(frozen=True)
class Midia:
    """Arquivo enviado ao modelo (imagem ou PDF)."""

    dados: bytes
    mime: MimeMidia


@dataclass(frozen=True)
class Correcao:
    """Tentativa anterior que falhou na validação e a mensagem de erro devolvida ao modelo."""

    resposta_anterior: str
    mensagem_erro: str


@dataclass(frozen=True)
class RespostaLLM:
    texto: str
    tokens_entrada: int
    tokens_saida: int  # inclui tokens de raciocínio
    modelo: str


class ProvedorErro(Exception):
    """Falha na chamada ao provedor (rede, cota, chave inválida...)."""


class RespostaTruncadaErro(ProvedorErro):
    """O modelo atingiu o limite de tokens de saída antes de terminar o JSON."""


class RespostaBloqueadaErro(ProvedorErro):
    """O provedor bloqueou o pedido ou não devolveu conteúdo."""


class ProvedorLLM(ABC):
    """Gera JSON a partir de mídias + instruções, seguindo um JSON Schema."""

    nome: ClassVar[str]
    modelo_padrao: ClassVar[str]

    def __init__(self, modelo: str | None = None) -> None:
        self.modelo = modelo or self.modelo_padrao

    @abstractmethod
    def gerar_json(
        self,
        *,
        instrucoes: str,
        midias: Sequence[Midia],
        schema: dict[str, Any],
        correcoes: Sequence[Correcao] = (),
    ) -> RespostaLLM:
        """Faz uma chamada; ``correcoes`` viram turnos extras da conversa, em ordem."""
