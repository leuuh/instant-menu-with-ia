"""Interface de ponta a ponta com o AppTest do Streamlit e o provedor fake (sem rede)."""

import io
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import pagina
from core.config import Config, ConfigErro
from core.providers.base import Midia, ProvedorErro, ProvedorLLM
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


def _foto_com_largura(largura: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (largura, 600), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def _json_item(nome: str) -> str:
    return json.dumps(
        {
            "info_restaurante": {"nome": None, "telefone": None, "horario": None},
            "categorias": [
                {
                    "nome": "Lanches",
                    "categoria_inferida": False,
                    "itens": [
                        {
                            "nome": nome,
                            "descricao_original": None,
                            "preco": 10.0,
                            "variacoes": [],
                            "adicionais": [],
                            "alergenicos_provaveis": [],
                            "confianca": 0.95,
                            "observacao": None,
                        }
                    ],
                }
            ],
        }
    )


def _por_largura(midias: Sequence[Midia]) -> str:
    largura = Image.open(io.BytesIO(midias[0].dados)).width
    if largura == 999:
        raise ProvedorErro("cota esgotada")
    return _json_item(f"Item {largura}")


def _botao(app: AppTest, rotulo: str) -> Any:
    return next(botao for botao in app.button if botao.label == rotulo)


def _enviar_varios(app: AppTest, larguras: Sequence[int]) -> None:
    arquivos = [(f"{n}.jpg", _foto_com_largura(n), "image/jpeg") for n in larguras]
    app.file_uploader[0].set_value(arquivos).run()
    app.button[0].click().run()


def test_varias_fotos_viram_uma_tabela(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    provedor = ProvedorFake(responder=_por_largura)
    app = abrir_app(lambda _config: provedor)
    _enviar_varios(app, [300, 400])

    assert not app.exception
    extracao = app.session_state[pagina.CHAVE_EXTRACAO]
    assert sorted(extracao.tabela["nome"]) == ["Item 300", "Item 400"]
    assert len(provedor.chamadas) == 2


def test_foto_que_falha_aparece_como_aviso(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    app = abrir_app(lambda _config: ProvedorFake(responder=_por_largura))
    _enviar_varios(app, [300, 999])

    assert not app.exception
    assert not app.error
    assert "999.jpg: não foi possível ler" in app.warning[0].value
    assert list(app.session_state[pagina.CHAVE_EXTRACAO].tabela["nome"]) == ["Item 300"]


def test_selecao_acima_do_limite_nao_chama_o_modelo(
    abrir_app: Callable[[CriarProvedor], AppTest],
) -> None:
    provedor = ProvedorFake(responder=_por_largura)
    app = abrir_app(lambda _config: provedor)
    _enviar_varios(app, [300, 310, 320, 330, 340, 350])

    assert "no máximo 5" in app.error[0].value
    assert provedor.chamadas == []


def test_painel_mostra_tempo_e_custo(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    provedor = ProvedorFake(modelo="gemini-3.5-flash-lite", responder=_por_largura)
    app = abrir_app(lambda _config: provedor)
    _enviar_varios(app, [300, 400])

    metricas = {metrica.label: metrica.value for metrica in app.metric}
    # 2000 de entrada a US$ 0,30 e 1000 de saída a US$ 2,50 por milhão
    assert metricas["Custo estimado"] == "US$ 0,0031"
    assert metricas["Em reais"] == "R$ 0,02"
    assert metricas["Itens lidos"] == "2"
    assert metricas["Tempo de processamento"].endswith(" s")


def test_painel_sem_preco_cadastrado(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    app = abrir_app(lambda _config: ProvedorFake(responder=_por_largura))
    _enviar_varios(app, [300])
    metricas = {metrica.label: metrica.value for metrica in app.metric}
    assert metricas["Custo estimado"] == "não cadastrado"
    assert "Em reais" not in metricas


def _responder_com_descricoes(midias: Sequence[Midia]) -> str:
    if midias:
        return _por_largura(midias)
    return json.dumps({"descricoes": [{"id": 0, "descricao": "Item 300 para matar a fome"}]})


def test_gerar_descricoes_preserva_a_tabela_e_soma_no_painel(
    abrir_app: Callable[[CriarProvedor], AppTest],
) -> None:
    provedor = ProvedorFake(modelo="gemini-3.5-flash-lite", responder=_responder_com_descricoes)
    app = abrir_app(lambda _config: provedor)
    _enviar_varios(app, [300])
    custo_antes = {m.label: m.value for m in app.metric}["Custo estimado"]

    _botao(app, "Gerar descrições sugeridas").click().run()

    assert not app.exception
    extracao = app.session_state[pagina.CHAVE_EXTRACAO]
    assert extracao.tabela.loc[0, "descricao_sugerida"] == "Item 300 para matar a fome"
    assert not extracao.tabela.loc[0, "usar_sugestao"]
    assert extracao.versao_tabela == 1
    assert "1 descrição(ões) sugerida(s)" in app.info[0].value
    assert provedor.chamadas[-1].midias == []
    assert {m.label: m.value for m in app.metric}["Custo estimado"] != custo_antes


def test_descricao_descartada_e_informada(abrir_app: Callable[[CriarProvedor], AppTest]) -> None:
    def responder(midias: Sequence[Midia]) -> str:
        if midias:
            return _por_largura(midias)
        return json.dumps({"descricoes": [{"id": 0, "descricao": "Com 2 queijos"}]})

    app = abrir_app(lambda _config: ProvedorFake(responder=responder))
    _enviar_varios(app, [300])
    _botao(app, "Gerar descrições sugeridas").click().run()

    assert "1 descartada(s)" in app.info[0].value
    assert app.session_state[pagina.CHAVE_EXTRACAO].tabela.loc[0, "descricao_sugerida"] == ""


def test_usar_e_desmarcar_todas_as_sugestoes(
    abrir_app: Callable[[CriarProvedor], AppTest],
) -> None:
    app = abrir_app(lambda _config: ProvedorFake(responder=_responder_com_descricoes))
    _enviar_varios(app, [300])
    _botao(app, "Gerar descrições sugeridas").click().run()

    _botao(app, "Usar todas as sugestões").click().run()
    assert app.session_state[pagina.CHAVE_EXTRACAO].tabela.loc[0, "usar_sugestao"]

    _botao(app, "Manter todas as originais").click().run()
    assert not app.session_state[pagina.CHAVE_EXTRACAO].tabela.loc[0, "usar_sugestao"]
    assert not app.exception


def test_falha_ao_gerar_descricoes_nao_perde_a_tabela(
    abrir_app: Callable[[CriarProvedor], AppTest],
) -> None:
    def responder(midias: Sequence[Midia]) -> str:
        if midias:
            return _por_largura(midias)
        raise ProvedorErro("cota esgotada")

    app = abrir_app(lambda _config: ProvedorFake(responder=responder))
    _enviar_varios(app, [300])
    _botao(app, "Gerar descrições sugeridas").click().run()

    assert not app.exception
    assert "Não foi possível gerar as descrições" in app.error[0].value
    extracao = app.session_state[pagina.CHAVE_EXTRACAO]
    assert list(extracao.tabela["nome"]) == ["Item 300"]
    assert extracao.tem_sugestoes is False
