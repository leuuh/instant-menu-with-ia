"""Provedor Google Gemini (SDK google-genai)."""

import time
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from core.providers.base import (
    Correcao,
    Midia,
    ProvedorErro,
    ProvedorLLM,
    RespostaBloqueadaErro,
    RespostaLLM,
    RespostaTruncadaErro,
)

TENTATIVAS_HTTP = 3  # retry do SDK para 429/5xx e timeout; independe das correções de validação
TIMEOUT_HTTP_MS = 120_000  # por tentativa; sem limite, uma chamada presa espera indefinidamente
ERROS_CONEXAO = (httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)  # o SDK não repete
PAUSA_RECONEXAO_S = 2.0
# Em fotos reais, a resolução padrão gerou mais erros de leitura; ver docs/decisoes.md.
RESOLUCAO_IMAGEM = types.PartMediaResolutionLevel.MEDIA_RESOLUTION_ULTRA_HIGH
FINAIS_NORMAIS = {None, types.FinishReason.STOP, types.FinishReason.FINISH_REASON_UNSPECIFIED}


class ProvedorGemini(ProvedorLLM):
    nome = "gemini"
    modelo_padrao = "gemini-3.8-flash"

    def __init__(
        self,
        modelo: str | None = None,
        *,
        api_key: str | None = None,
        cliente: genai.Client | None = None,
        max_tokens_saida: int = 32768,
    ) -> None:
        super().__init__(modelo)
        self._cliente = cliente or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_HTTP_MS,
                retry_options=types.HttpRetryOptions(attempts=TENTATIVAS_HTTP),
            ),
        )
        self._max_tokens_saida = max_tokens_saida

    def gerar_json(
        self,
        *,
        instrucoes: str,
        midias: Sequence[Midia],
        schema: dict[str, Any],
        correcoes: Sequence[Correcao] = (),
    ) -> RespostaLLM:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema,
            max_output_tokens=self._max_tokens_saida,
        )
        conversa = montar_conversa(instrucoes, midias, correcoes)
        try:
            resposta = self._chamar_reconectando(conversa, config)
        except errors.APIError as erro:
            raise ProvedorErro(f"Gemini retornou erro {erro.code}: {erro.message}") from erro
        except httpx.TimeoutException as erro:
            limite_s = TIMEOUT_HTTP_MS // 1000
            raise ProvedorErro(f"Gemini não respondeu em {limite_s} s por tentativa.") from erro
        except httpx.HTTPError as erro:
            raise ProvedorErro(f"Falha de rede ao chamar o Gemini: {erro}") from erro
        return RespostaLLM(
            texto=_extrair_texto(resposta),
            tokens_entrada=_tokens_entrada(resposta),
            tokens_saida=_tokens_saida(resposta),
            modelo=self.modelo,
        )

    def _chamar_reconectando(
        self, conversa: list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        """Repete quando a conexão cai no meio da resposta; a última falha chega a quem chamou."""
        for tentativa in range(1, TENTATIVAS_HTTP):
            try:
                return self._gerar(conversa, config)
            except ERROS_CONEXAO:
                time.sleep(PAUSA_RECONEXAO_S * tentativa)
        return self._gerar(conversa, config)

    def _gerar(
        self, conversa: list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        return self._cliente.models.generate_content(
            model=self.modelo, contents=conversa, config=config
        )


def montar_conversa(
    instrucoes: str, midias: Sequence[Midia], correcoes: Sequence[Correcao]
) -> list[types.Content]:
    """Turno do usuário (mídias + instruções) seguido de pares modelo/usuário de correção."""
    partes = [_parte_da_midia(m) for m in midias]
    conversa = [types.Content(role="user", parts=[*partes, types.Part(text=instrucoes)])]
    for correcao in correcoes:
        conversa.append(
            types.Content(role="model", parts=[types.Part(text=correcao.resposta_anterior)])
        )
        conversa.append(types.Content(role="user", parts=[types.Part(text=correcao.mensagem_erro)]))
    return conversa


def _parte_da_midia(midia: Midia) -> types.Part:
    """Imagem usa a resolução máxima; PDF fica no padrão, pois o texto já vem no arquivo."""
    resolucao = None if midia.mime == "application/pdf" else RESOLUCAO_IMAGEM
    return types.Part.from_bytes(data=midia.dados, mime_type=midia.mime, media_resolution=resolucao)


def _extrair_texto(resposta: types.GenerateContentResponse) -> str:
    feedback = resposta.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise RespostaBloqueadaErro(f"Pedido bloqueado pelo Gemini: {feedback.block_reason}")
    if not resposta.candidates:
        raise RespostaBloqueadaErro("Gemini não devolveu nenhuma resposta.")
    final = resposta.candidates[0].finish_reason
    if final == types.FinishReason.MAX_TOKENS:
        raise RespostaTruncadaErro("Resposta cortada no limite de tokens de saída.")
    if final not in FINAIS_NORMAIS:
        raise RespostaBloqueadaErro(f"Gemini encerrou a resposta com motivo {final}.")
    if not resposta.text:
        raise RespostaBloqueadaErro("Gemini devolveu resposta vazia.")
    return resposta.text


def _tokens_entrada(resposta: types.GenerateContentResponse) -> int:
    uso = resposta.usage_metadata
    return (uso.prompt_token_count or 0) if uso else 0


def _tokens_saida(resposta: types.GenerateContentResponse) -> int:
    uso = resposta.usage_metadata
    if uso is None:
        return 0
    return (uso.candidates_token_count or 0) + (uso.thoughts_token_count or 0)
