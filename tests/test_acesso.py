import io
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest

from app import pagina
from app.acesso import LimiteDiario, senha_confere
from core.config import Config
from core.providers.fake import ProvedorFake

SCRIPT = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


def test_limite_diario_bloqueia_depois_do_limite() -> None:
    limite = LimiteDiario(2)
    assert [limite.consumir() for _ in range(3)] == [True, True, False]
    assert limite.restantes() == 0


def test_limite_diario_volta_no_dia_seguinte() -> None:
    dias = iter([date(2026, 11, 3), date(2026, 11, 3), date(2026, 11, 3), date(2026, 11, 4)])
    limite = LimiteDiario(1, hoje=lambda: next(dias))
    assert limite.consumir() is True
    assert limite.consumir() is False
    assert limite.consumir() is True


def test_limite_diario_e_seguro_com_varias_sessoes_ao_mesmo_tempo() -> None:
    limite = LimiteDiario(50)
    resultados: list[bool] = []

    def usar() -> None:
        for _ in range(20):
            resultados.append(limite.consumir())

    threads = [threading.Thread(target=usar) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert resultados.count(True) == 50


def test_senha_confere() -> None:
    assert senha_confere("cardápio", "cardápio")
    assert not senha_confere("cardapio", "cardápio")
    assert not senha_confere("", "x")


def _foto() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 600), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def abrir(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> Callable[..., tuple[AppTest, ProvedorFake]]:
    def abrir_com(json_resposta: str = "", **ajustes: Any) -> tuple[AppTest, ProvedorFake]:
        provedor = ProvedorFake(responder=lambda _midias: json_resposta)
        pagina.limite_diario.clear()
        monkeypatch.setattr(pagina, "Config", lambda: config.model_copy(update=ajustes))
        monkeypatch.setattr(pagina, "criar_provedor", lambda _config: provedor)
        return AppTest.from_file(SCRIPT, default_timeout=30).run(), provedor

    return abrir_com


def _botao(app: AppTest, rotulo: str) -> Any:
    return next(botao for botao in app.button if botao.label == rotulo)


def _enviar_foto(app: AppTest) -> None:
    app.file_uploader[0].set_value(("cardapio.jpg", _foto(), "image/jpeg")).run()


def test_sem_senha_configurada_a_ia_fica_liberada(
    abrir: Callable[..., tuple[AppTest, ProvedorFake]], json_valido: str
) -> None:
    app, provedor = abrir(json_valido)
    _enviar_foto(app)
    assert len(app.sidebar.text_input) == 0
    _botao(app, "Extrair cardápio").click().run()
    assert len(provedor.chamadas) == 1


def test_com_senha_a_extracao_fica_bloqueada_ate_digitar(
    abrir: Callable[..., tuple[AppTest, ProvedorFake]], json_valido: str
) -> None:
    app, provedor = abrir(json_valido, senha_acesso=SecretStr("segredo"))
    _enviar_foto(app)

    assert _botao(app, "Extrair cardápio").disabled is True
    assert "pede uma senha" in app.info[0].value

    app.sidebar.text_input(key=pagina.CHAVE_SENHA).input("errada").run()
    assert "Senha incorreta" in app.sidebar.error[0].value
    assert _botao(app, "Extrair cardápio").disabled is True

    app.sidebar.text_input(key=pagina.CHAVE_SENHA).input("segredo").run()
    _botao(app, "Extrair cardápio").click().run()
    assert not app.exception
    assert len(provedor.chamadas) == 1


def test_limite_diario_atingido_nao_chama_o_modelo(
    abrir: Callable[..., tuple[AppTest, ProvedorFake]], json_valido: str
) -> None:
    app, provedor = abrir(json_valido, max_usos_ia_por_dia=1)
    _enviar_foto(app)
    _botao(app, "Extrair cardápio").click().run()
    _botao(app, "Extrair cardápio").click().run()

    assert len(provedor.chamadas) == 1
    assert "limite diário" in app.error[0].value


def test_exemplo_pronto_nao_chama_o_modelo_nem_pede_senha(
    abrir: Callable[..., tuple[AppTest, ProvedorFake]],
) -> None:
    app, provedor = abrir(senha_acesso=SecretStr("segredo"))
    _botao(app, "Ver um exemplo pronto").click().run()

    assert not app.exception
    assert provedor.chamadas == []
    extracao = app.session_state[pagina.CHAVE_EXTRACAO]
    assert extracao.exemplo is True
    assert extracao.resultado.cardapio.total_itens() == 11
    assert any("Exemplo pronto" in info.value for info in app.info)
    assert _botao(app, "Gerar descrições sugeridas").disabled is True
    assert [botao.label for botao in app.download_button] == ["Baixar JSON", "Baixar CSV"]


def test_descricoes_tambem_consomem_o_limite(
    abrir: Callable[..., tuple[AppTest, ProvedorFake]],
) -> None:
    app, provedor = abrir('{"descricoes": []}', max_usos_ia_por_dia=1)
    _botao(app, "Ver um exemplo pronto").click().run()  # o exemplo não gasta o limite
    _botao(app, "Gerar descrições sugeridas").click().run()  # gasta o único uso
    assert len(provedor.chamadas) == 1
    _botao(app, "Gerar descrições sugeridas").click().run()
    assert len(provedor.chamadas) == 1
    assert any("limite diário" in erro.value for erro in app.error)
