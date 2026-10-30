"""Registro de provedores. Trocar de provedor = mudar LLM_PROVIDER no .env."""

from collections.abc import Callable

from core.config import Config, ConfigErro
from core.providers.base import ProvedorLLM


def _criar_gemini(config: Config) -> ProvedorLLM:
    from core.providers.gemini import ProvedorGemini

    if config.gemini_api_key is None:
        raise ConfigErro("GEMINI_API_KEY não definida. Copie .env.example para .env e preencha.")
    return ProvedorGemini(config.llm_model, api_key=config.gemini_api_key.get_secret_value())


FABRICAS: dict[str, Callable[[Config], ProvedorLLM]] = {
    "gemini": _criar_gemini,
}


def criar_provedor(config: Config) -> ProvedorLLM:
    """Instancia o provedor configurado em ``config.llm_provider``."""
    fabrica = FABRICAS.get(config.llm_provider)
    if fabrica is None:
        disponiveis = ", ".join(sorted(FABRICAS))
        raise ConfigErro(
            f"Provedor '{config.llm_provider}' desconhecido. Disponíveis: {disponiveis}."
        )
    return fabrica(config)
