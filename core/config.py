"""Configuração lida do ambiente e do arquivo .env."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_PROJETO = Path(__file__).resolve().parents[1]


class Config(BaseSettings):
    """Configuração da aplicação. Variáveis de ambiente têm prioridade sobre o .env."""

    model_config = SettingsConfigDict(
        env_file=RAIZ_PROJETO / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    llm_provider: str = "gemini"
    llm_model: str | None = None  # None = modelo padrão do provedor
    gemini_api_key: SecretStr | None = None
    limiar_confianca: float = Field(default=0.7, ge=0, le=1)
    max_correcoes: int = Field(default=2, ge=0)
    max_lado_imagem: int = Field(default=3072, ge=256)
    dir_logs: Path = RAIZ_PROJETO / "logs"


class ConfigErro(Exception):
    """Configuração ausente ou inválida."""
