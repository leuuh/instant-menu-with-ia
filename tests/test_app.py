"""Interface de ponta a ponta com o AppTest do Streamlit e o provedor fake (sem rede)."""

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import pagina
from core.config import Config, ConfigErro
from core.providers.base import ProvedorLLM
from core.providers.fake import ProvedorFake

SCRIPT = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")

CriarProvedor = Callable[[Config], ProvedorLLM]


def _foto() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 600), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def abrir_app(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> Callable[[CriarProvedor], AppTest]:
    def abrir(criar: CriarProvedor) -> AppTest:
        monkeypatch.setattr(pagina, "Config", lambda: config)
        monkeypatch.setattr(pagina, "criar_provedor", criar)
        return AppTest.from_file(SCRIPT, default_timeout=30).run()

    return abrir


def _enviar(app: AppTest, nome: str, dados: bytes, mime: str) -> None:
    app.file_uploader[0].set_value((nome, dados, mime)).run()
    app.button[0].click().run()


def test_abre_com_o_botao_desativado(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    app = abrir_app(lambda _config: ProvedorFake([]))
    assert not app.exception
    assert app.button[0].disabled is True
    assert len(app.download_button) == 0


def test_extrai_e_destaca_o_que_precisa_de_revisao(
    abrir_app: Callable[[CriarProvedor], AppTest], json_valido: str
) -> None:
    app = abrir_app(lambda _config: ProvedorFake([json_valido]))
    _enviar(app, "cardapio.jpg", _foto(), "image/jpeg")

    assert not app.exception
    assert not app.error
    aviso = app.warning[0].value
    assert "3 item(ns) para revisar" in aviso
    assert "**X-Salada** (Lanches): leitura incerta, sem preço" in aviso
    assert app.text_input[0].value == "Lanchonete Sabor da Praça"
    assert [botao.label for botao in app.download_button] == ["Baixar JSON", "Baixar CSV"]
    assert all(not botao.disabled for botao in app.download_button)


def test_tabela_comeca_com_o_alerta_visivel(
    abrir_app: Callable[[CriarProvedor], AppTest], json_valido: str
) -> None:
    app = abrir_app(lambda _config: ProvedorFake([json_valido]))
    _enviar(app, "cardapio.jpg", _foto(), "image/jpeg")
    extracao = app.session_state[pagina.CHAVE_EXTRACAO]
    assert extracao.tabela.loc[1, "alerta"] == "⚠️ leitura incerta, sem preço"
    assert extracao.tabela.loc[0, "alerta"] == ""


def test_aceita_pdf(abrir_app: Callable[[CriarProvedor], AppTest], json_valido: str) -> None:
    provedor = ProvedorFake([json_valido])
    app = abrir_app(lambda _config: provedor)
    _enviar(app, "cardapio.pdf", b"%PDF-1.7\nconteudo", "application/pdf")

    assert not app.exception
    assert provedor.chamadas[0].midias[0].mime == "application/pdf"
    assert "PDF enviado: cardapio.pdf" in app.info[0].value


def test_arquivo_corrompido_mostra_mensagem(
    abrir_app: Callable[[CriarProvedor], AppTest], json_valido: str
) -> None:
    provedor = ProvedorFake([json_valido])
    app = abrir_app(lambda _config: provedor)
    _enviar(app, "falso.jpg", b"isto nao e uma imagem", "image/jpeg")

    assert not app.exception
    assert "não é uma imagem válida" in app.error[0].value
    assert provedor.chamadas == []  # não gasta chamada de API com arquivo ruim


def test_falha_do_provedor_mostra_mensagem(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    app = abrir_app(lambda _config: ProvedorFake([]))
    _enviar(app, "cardapio.jpg", _foto(), "image/jpeg")

    assert not app.exception
    assert "Não foi possível ler o cardápio" in app.error[0].value
    assert len(app.download_button) == 0


def test_chave_ausente_mostra_mensagem(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    def sem_chave(_config: Config) -> ProvedorLLM:
        raise ConfigErro("GEMINI_API_KEY não definida.")

    app = abrir_app(sem_chave)
    _enviar(app, "cardapio.jpg", _foto(), "image/jpeg")

    assert not app.exception
    assert "GEMINI_API_KEY" in app.error[0].value


def test_cardapio_sem_itens_avisa(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    vazio = (
        '{"info_restaurante": {"nome": null, "telefone": null, "horario": null}, "categorias": []}'
    )
    app = abrir_app(lambda _config: ProvedorFake([vazio]))
    _enviar(app, "parede.jpg", _foto(), "image/jpeg")

    assert not app.exception
    assert "Nenhum item foi encontrado" in app.warning[0].value


def test_nova_extracao_troca_a_tabela(
    abrir_app: Callable[[CriarProvedor], AppTest], json_valido: str
) -> None:
    app = abrir_app(lambda _config: ProvedorFake([json_valido, json_valido]))
    _enviar(app, "um.jpg", _foto(), "image/jpeg")
    primeira = app.session_state[pagina.CHAVE_EXTRACAO].versao
    app.button[0].click().run()
    assert app.session_state[pagina.CHAVE_EXTRACAO].versao == primeira + 1
    assert not app.exception
