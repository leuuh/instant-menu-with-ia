"""Testes do provedor Gemini com o cliente do SDK simulado (sem rede)."""

from typing import Any

import httpx
import pytest
from google.genai import errors, types

from core.providers.base import (
    Correcao,
    Midia,
    ProvedorErro,
    RespostaBloqueadaErro,
    RespostaTruncadaErro,
)
from core.providers.gemini import TENTATIVAS_HTTP, TIMEOUT_HTTP_MS, ProvedorGemini

MIDIA = Midia(dados=b"\xff\xd8fake-jpeg", mime="image/jpeg")
SCHEMA = {"type": "object"}


def _resposta(
    texto: str = '{"ok": true}',
    final: types.FinishReason = types.FinishReason.STOP,
    bloqueio: types.BlockedReason | None = None,
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=texto)]),
                finish_reason=final,
            )
        ],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=bloqueio)
        if bloqueio
        else None,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1200, candidates_token_count=300, thoughts_token_count=150
        ),
    )


class _ModelsFalso:
    def __init__(self, resultado: types.GenerateContentResponse | Exception) -> None:
        self.resultado = resultado
        self.chamadas: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.chamadas.append(kwargs)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


class _ClienteFalso:
    def __init__(self, resultado: types.GenerateContentResponse | Exception) -> None:
        self.models = _ModelsFalso(resultado)


def _provedor(resultado: types.GenerateContentResponse | Exception) -> ProvedorGemini:
    return ProvedorGemini(cliente=_ClienteFalso(resultado))  # type: ignore[arg-type]


def _chamada(provedor: ProvedorGemini) -> dict[str, Any]:
    chamadas: list[dict[str, Any]] = provedor._cliente.models.chamadas  # type: ignore[attr-defined]
    return chamadas[0]


def test_monta_requisicao_com_midia_instrucoes_e_schema() -> None:
    provedor = _provedor(_resposta())
    provedor.gerar_json(instrucoes="extraia", midias=[MIDIA], schema=SCHEMA)

    chamada = _chamada(provedor)
    assert chamada["model"] == "gemini-3.8-flash"
    assert chamada["config"].response_mime_type == "application/json"
    assert chamada["config"].response_json_schema == SCHEMA
    (turno,) = chamada["contents"]
    assert turno.role == "user"
    assert turno.parts[0].inline_data.mime_type == "image/jpeg"
    assert turno.parts[0].inline_data.data == MIDIA.dados
    assert turno.parts[1].text == "extraia"


def test_correcoes_viram_turnos_modelo_e_usuario() -> None:
    provedor = _provedor(_resposta())
    correcoes = [Correcao("{ruim1}", "erro 1"), Correcao("{ruim2}", "erro 2")]
    provedor.gerar_json(instrucoes="extraia", midias=[MIDIA], schema=SCHEMA, correcoes=correcoes)

    contents = _chamada(provedor)["contents"]
    assert [c.role for c in contents] == ["user", "model", "user", "model", "user"]
    assert [c.parts[0].text for c in contents[1:]] == ["{ruim1}", "erro 1", "{ruim2}", "erro 2"]


def test_le_texto_e_soma_tokens_de_raciocinio_na_saida() -> None:
    resposta = _provedor(_resposta()).gerar_json(instrucoes="x", midias=[MIDIA], schema=SCHEMA)
    assert resposta.texto == '{"ok": true}'
    assert (resposta.tokens_entrada, resposta.tokens_saida) == (1200, 450)
    assert resposta.modelo == "gemini-3.8-flash"


def test_modelo_configuravel() -> None:
    provedor = ProvedorGemini("gemini-3.5-flash-lite", cliente=_ClienteFalso(_resposta()))  # type: ignore[arg-type]
    provedor.gerar_json(instrucoes="x", midias=[MIDIA], schema=SCHEMA)
    assert _chamada(provedor)["model"] == "gemini-3.5-flash-lite"


def test_resposta_truncada() -> None:
    provedor = _provedor(_resposta(final=types.FinishReason.MAX_TOKENS))
    with pytest.raises(RespostaTruncadaErro):
        provedor.gerar_json(instrucoes="x", midias=[MIDIA], schema=SCHEMA)


@pytest.mark.parametrize(
    "resposta",
    [
        _resposta(bloqueio=types.BlockedReason.SAFETY),
        _resposta(final=types.FinishReason.SAFETY),
        _resposta(texto=""),
        types.GenerateContentResponse(candidates=[]),
    ],
)
def test_resposta_bloqueada_ou_vazia(resposta: types.GenerateContentResponse) -> None:
    with pytest.raises(RespostaBloqueadaErro):
        _provedor(resposta).gerar_json(instrucoes="x", midias=[MIDIA], schema=SCHEMA)


def test_erro_da_api_vira_provedor_erro() -> None:
    erro = errors.ClientError(
        429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    )
    with pytest.raises(ProvedorErro, match="429"):
        _provedor(erro).gerar_json(instrucoes="x", midias=[MIDIA], schema=SCHEMA)


@pytest.mark.parametrize(
    ("erro", "mensagem"),
    [
        (httpx.ReadTimeout("lento"), "não respondeu"),
        (httpx.ConnectTimeout("lento"), "não respondeu"),
        (httpx.ReadError("conexão derrubada"), "Falha de rede"),
        (httpx.ConnectError("sem rota"), "Falha de rede"),
    ],
)
def test_erro_de_rede_vira_provedor_erro(erro: httpx.HTTPError, mensagem: str) -> None:
    with pytest.raises(ProvedorErro, match=mensagem):
        _provedor(erro).gerar_json(instrucoes="x", midias=[MIDIA], schema=SCHEMA)


def test_cliente_real_tem_timeout_e_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: dict[str, Any] = {}

    def cliente_falso(**kwargs: Any) -> _ClienteFalso:
        capturado.update(kwargs)
        return _ClienteFalso(_resposta())

    monkeypatch.setattr("core.providers.gemini.genai.Client", cliente_falso)
    ProvedorGemini(api_key="chave-de-teste")

    opcoes = capturado["http_options"]
    assert opcoes.timeout == TIMEOUT_HTTP_MS
    assert opcoes.retry_options.attempts == TENTATIVAS_HTTP
