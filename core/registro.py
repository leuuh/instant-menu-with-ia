"""Log estruturado de cada extração (console + arquivo JSON Lines)."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARQUIVO_LOG = "extracoes.jsonl"

logger = logging.getLogger("cardapio")


def registrar_extracao(evento: dict[str, Any], dir_logs: Path) -> None:
    """Acrescenta o evento com timestamp em ``dir_logs/extracoes.jsonl`` e no logger."""
    linha = json.dumps(
        {"timestamp": datetime.now(UTC).isoformat(timespec="seconds"), **evento},
        ensure_ascii=False,
        default=str,
    )
    dir_logs.mkdir(parents=True, exist_ok=True)
    with (dir_logs / ARQUIVO_LOG).open("a", encoding="utf-8") as arquivo:
        arquivo.write(linha + "\n")
    logger.info(linha)
