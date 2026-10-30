import json
from pathlib import Path
from typing import Any

import pytest

from core.config import Config

DIR_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def json_valido() -> str:
    return (DIR_FIXTURES / "extracao_valida.json").read_text(encoding="utf-8")


@pytest.fixture
def dados_validos(json_valido: str) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads(json_valido)
    return dados


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Config isolada: ignora o .env real e grava logs em pasta temporária."""
    return Config(_env_file=None, dir_logs=tmp_path / "logs")  # type: ignore[call-arg]
