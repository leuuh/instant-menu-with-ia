import json
from pathlib import Path

import pytest
from PIL import Image

from core import cli
from core.config import Config
from core.providers.fake import ProvedorFake


@pytest.fixture
def foto(tmp_path: Path) -> Path:
    caminho = tmp_path / "cardapio.jpg"
    Image.new("RGB", (400, 600), "white").save(caminho)
    return caminho


@pytest.fixture(autouse=True)
def isolar(monkeypatch: pytest.MonkeyPatch, config: Config, json_valido: str) -> None:
    """CLI usa a config de teste e o provedor fake, sem rede e sem .env real."""
    monkeypatch.setattr(cli, "Config", lambda: config)
    monkeypatch.setattr(cli, "criar_provedor", lambda _config: ProvedorFake([json_valido]))


def test_extrair_grava_json_e_imprime_resumo(
    foto: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    saida = tmp_path / "saida" / "cardapio.json"
    assert cli.main(["extrair", str(foto), "--saida", str(saida)]) == 0

    dados = json.loads(saida.read_text(encoding="utf-8"))
    assert dados["cardapio"]["categorias"][0]["itens"][0]["preco"] == 32.9
    assert dados["metricas"]["tentativas"] == 1
    resumo = capsys.readouterr().err
    assert "4 itens" in resumo
    assert "Lanches / X-Salada: confianca_baixa, preco_ausente" in resumo


def test_sem_saida_imprime_json_no_stdout(foto: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["extrair", str(foto)]) == 0
    assert json.loads(capsys.readouterr().out)["cardapio"]["info_restaurante"]["nome"]


def test_arquivo_inexistente_retorna_erro(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["extrair", str(tmp_path / "nao_existe.jpg")]) == 1
    assert "não encontrado" in capsys.readouterr().err


def test_imagem_invalida_retorna_erro(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    falso = tmp_path / "falso.jpg"
    falso.write_text("texto", encoding="utf-8")
    assert cli.main(["extrair", str(falso)]) == 1
    assert "não é uma imagem válida" in capsys.readouterr().err
