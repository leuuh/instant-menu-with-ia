"""Provedor determinístico para testes: devolve respostas pré-programadas."""

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from core.providers.base import Correcao, Midia, ProvedorErro, ProvedorLLM, RespostaLLM


@dataclass(frozen=True)
class ChamadaRegistrada:
    instrucoes: str
    midias: list[Midia]
    schema: dict[str, Any]
    correcoes: list[Correcao]


class ProvedorFake(ProvedorLLM):
    nome = "fake"
    modelo_padrao = "fake-modelo"

    def __init__(
        self,
        respostas: Sequence[str] = (),
        modelo: str | None = None,
        tokens_entrada: int = 1000,
        tokens_saida: int = 500,
        responder: Callable[[Sequence[Midia]], str] | None = None,
    ) -> None:
        super().__init__(modelo)
        self._respostas = deque(respostas)
        self._tokens_entrada = tokens_entrada
        self._tokens_saida = tokens_saida
        self._responder = responder  # chamadas em paralelo: a resposta depende da mídia
        self.chamadas: list[ChamadaRegistrada] = []

    def gerar_json(
        self,
        *,
        instrucoes: str,
        midias: Sequence[Midia],
        schema: dict[str, Any],
        correcoes: Sequence[Correcao] = (),
    ) -> RespostaLLM:
        self.chamadas.append(ChamadaRegistrada(instrucoes, list(midias), schema, list(correcoes)))
        if self._responder is None and not self._respostas:
            raise ProvedorErro("ProvedorFake sem respostas programadas.")
        return RespostaLLM(
            texto=self._responder(midias) if self._responder else self._respostas.popleft(),
            tokens_entrada=self._tokens_entrada,
            tokens_saida=self._tokens_saida,
            modelo=self.modelo,
        )
