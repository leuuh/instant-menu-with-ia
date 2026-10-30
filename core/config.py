"""Configuração lida do ambiente e do arquivo .env."""

from decimal import Decimal
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
    llm_model_descricoes: str | None = None  # None = o mesmo modelo da extração
    gemini_api_key: SecretStr | None = None
    limiar_confianca: float = Field(default=0.9, ge=0, le=1)  # medido em fotos: ver decisoes.md
    max_correcoes: int = Field(default=2, ge=0)
    max_lado_imagem: int = Field(default=3072, ge=256)
    max_chamadas_paralelas: int = Field(default=3, ge=1)
    cotacao_usd_brl: Decimal = Field(default=Decimal("5.42"), gt=0)  # PTAX venda de 30/10/2026
    dir_logs: Path = RAIZ_PROJETO / "logs"

    def para_descricoes(self) -> "Config":
        """Mesma configuração, com o modelo escolhido para escrever as descrições."""
        return self.model_copy(update={"llm_model": self.llm_model_descricoes or self.llm_model})


class ConfigErro(Exception):
    """Configuração ausente ou inválida."""
