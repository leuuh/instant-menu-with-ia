"""Roda a extração nos cardápios com gabarito e compara modelos lado a lado.

Uso:
    python -m evals.run_evals --modelos gemini-3.5-flash-lite gemini-3.6-flash --repeticoes 3
    python -m evals.run_evals --reavaliar evals/resultados/2026-11-03_1530
    python -m evals.run_evals --retomar evals/resultados/2026-11-03_1530

Cada execução fica salva em JSON; ``--reavaliar`` recalcula o relatório sem chamar a API, e
``--retomar`` refaz só o que falhou (por exemplo, quando a cota diária da API acabou).
As fotos reais são baixadas da Wikimedia Commons para evals/cache/ (fora do git).
"""

import argparse
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core.config import RAIZ_PROJETO, Config
from core.extract import ERROS_EXTRACAO, extrair_arquivos
from core.providers import criar_provedor
from core.providers.base import ProvedorLLM
from core.schema import ResultadoExtracao
from evals.metricas import Contagem, Gabarito, carregar_gabarito, comparar

DIR_GABARITOS = RAIZ_PROJETO / "evals" / "data" / "gabaritos"
DIR_CACHE = RAIZ_PROJETO / "evals" / "cache"
DIR_RESULTADOS = RAIZ_PROJETO / "evals" / "resultados"
API_COMMONS = "https://commons.wikimedia.org/w/api.php"
AGENTE = "CardapioInstantaneo-evals/0.1 (https://github.com/leuuh/instant-menu-with-ia)"
PAUSA_DOWNLOAD_S = 3.0

CriarProvedor = Callable[[str], ProvedorLLM]


@dataclass
class Resumo:
    """Tudo o que uma combinação modelo x cardápio acumulou nas repetições."""

    contagem: Contagem = field(default_factory=Contagem)
    acuracias: list[float] = field(default_factory=list)
    tempos: list[float] = field(default_factory=list)
    custos: list[Decimal | None] = field(default_factory=list)
    falhas: int = 0
    problemas: list[str] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = _criar_parser().parse_args(argv)
    if args.reavaliar:
        pasta = Path(args.reavaliar)
    elif args.retomar:
        pasta = Path(args.retomar)
        execucao = json.loads((pasta / "execucao.json").read_text(encoding="utf-8"))
        config = Config()
        executar(
            execucao["modelos"],
            execucao["repeticoes"],
            carregar_gabaritos(),
            lambda modelo: criar_provedor(config.model_copy(update={"llm_model": modelo})),
            config,
            pasta=pasta,
        )
    else:
        config = Config()
        gabaritos = carregar_gabaritos(args.cardapios)
        pasta = executar(
            args.modelos,
            args.repeticoes,
            gabaritos,
            lambda modelo: criar_provedor(config.model_copy(update={"llm_model": modelo})),
            config,
        )
    print(escrever_relatorio(pasta))
    return 0


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.run_evals", description=__doc__)
    parser.add_argument("--modelos", nargs="+", default=["gemini-3.5-flash-lite"])
    parser.add_argument("--repeticoes", type=int, default=1)
    parser.add_argument("--cardapios", nargs="+", help="nomes dos gabaritos (padrão: todos)")
    parser.add_argument("--reavaliar", help="pasta de uma execução anterior: só refaz o relatório")
    parser.add_argument("--retomar", help="pasta de uma execução anterior: refaz o que falhou")
    return parser


def carregar_gabaritos(nomes: Sequence[str] | None = None) -> list[Gabarito]:
    caminhos = sorted(DIR_GABARITOS.glob("*.json"))
    gabaritos = [carregar_gabarito(caminho) for caminho in caminhos]
    if nomes:
        gabaritos = [g for g in gabaritos if g.cardapio in nomes]
        faltando = set(nomes) - {g.cardapio for g in gabaritos}
        if faltando:
            raise SystemExit(f"Gabarito não encontrado: {', '.join(sorted(faltando))}")
    return gabaritos


def executar(
    modelos: Sequence[str],
    repeticoes: int,
    gabaritos: Sequence[Gabarito],
    criar: CriarProvedor,
    config: Config,
    pasta: Path | None = None,
) -> Path:
    """Executa em sequência para o tempo medido ser o de um cardápio sozinho.

    Os modelos se alternam a cada cardápio: uma instabilidade do provedor afeta todos igualmente.
    """
    pasta = pasta or DIR_RESULTADOS / datetime.now().strftime("%Y-%m-%d_%H%M")
    pasta.mkdir(parents=True, exist_ok=True)
    arquivos = {g.cardapio: obter_arquivo(g) for g in gabaritos}
    if not (pasta / "execucao.json").exists():
        _salvar_execucao(pasta, modelos, repeticoes, config)
    for repeticao in range(1, repeticoes + 1):
        for gabarito in gabaritos:
            for modelo in modelos:
                destino = pasta / modelo / f"{gabarito.cardapio}_{repeticao}.json"
                if _ja_concluida(destino):
                    continue
                _rodar(arquivos[gabarito.cardapio], criar(modelo), config, destino)
                print(
                    f"[{repeticao}/{repeticoes}] {modelo} {gabarito.cardapio}: "
                    f"{_resumo_arquivo(destino)}"
                )
    return pasta


def _ja_concluida(destino: Path) -> bool:
    if not destino.exists():
        return False
    return "erro" not in json.loads(destino.read_text(encoding="utf-8"))


def _rodar(arquivo: Path, provedor: ProvedorLLM, config: Config, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        resultado = extrair_arquivos([arquivo], provedor, config)
    except ERROS_EXTRACAO as erro:
        destino.write_text(json.dumps({"erro": str(erro)}, ensure_ascii=False), encoding="utf-8")
        return
    destino.write_text(resultado.model_dump_json(indent=2), encoding="utf-8")


def _resumo_arquivo(destino: Path) -> str:
    dados = json.loads(destino.read_text(encoding="utf-8"))
    if "erro" in dados:
        return f"FALHOU ({dados['erro'].splitlines()[0][:80]})"
    itens = sum(len(c["itens"]) for c in dados["cardapio"]["categorias"])
    return f"{itens} itens em {dados['metricas']['tempo_s']} s"


def _salvar_execucao(pasta: Path, modelos: Sequence[str], repeticoes: int, config: Config) -> None:
    dados = {
        "data": datetime.now().isoformat(timespec="minutes"),
        "modelos": list(modelos),
        "repeticoes": repeticoes,
        "limiar_confianca": config.limiar_confianca,
    }
    (pasta / "execucao.json").write_text(json.dumps(dados, indent=2), encoding="utf-8")


def obter_arquivo(gabarito: Gabarito) -> Path:
    """Arquivo do repositório ou foto da Commons, baixada uma vez para evals/cache/."""
    if not gabarito.arquivo.startswith("http"):
        return RAIZ_PROJETO / gabarito.arquivo
    titulo = urllib.parse.unquote(gabarito.arquivo.rsplit("/wiki/", 1)[-1])
    extensao = Path(titulo).suffix.lower()
    destino = DIR_CACHE / f"{gabarito.cardapio}{extensao}"
    if not destino.exists():
        DIR_CACHE.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(_abrir(_url_do_arquivo(titulo)))
        time.sleep(PAUSA_DOWNLOAD_S)  # política de uso da Commons
    return destino


def _url_do_arquivo(titulo: str) -> str:
    consulta = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
            "titles": titulo,
        }
    )
    paginas = json.loads(_abrir(f"{API_COMMONS}?{consulta}"))["query"]["pages"]
    url: str = next(iter(paginas.values()))["imageinfo"][0]["url"]
    return url


def _abrir(url: str) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(pedido, timeout=120) as resposta:
        dados: bytes = resposta.read()
    return dados


# ---- relatório ----


def escrever_relatorio(pasta: Path) -> str:
    """Calcula as métricas de tudo o que está salvo na pasta e grava relatorio.md e detalhes.md."""
    execucao = json.loads((pasta / "execucao.json").read_text(encoding="utf-8"))
    gabaritos = {g.cardapio: g for g in carregar_gabaritos()}
    resumos = _resumir(pasta, execucao["modelos"], gabaritos)
    relatorio = _relatorio(execucao, gabaritos, resumos)
    (pasta / "relatorio.md").write_text(relatorio, encoding="utf-8")
    (pasta / "detalhes.md").write_text(_detalhes(resumos), encoding="utf-8")
    return relatorio


def _resumir(
    pasta: Path, modelos: Sequence[str], gabaritos: dict[str, Gabarito]
) -> dict[str, dict[str, Resumo]]:
    resumos: dict[str, dict[str, Resumo]] = {}
    for modelo in modelos:
        por_cardapio = resumos[modelo] = {}
        for arquivo in sorted((pasta / modelo).glob("*.json")):
            cardapio, repeticao = arquivo.stem.rsplit("_", 1)
            resumo = por_cardapio.setdefault(cardapio, Resumo())
            _acrescentar(resumo, gabaritos[cardapio], arquivo, repeticao)
    return resumos


def _acrescentar(resumo: Resumo, gabarito: Gabarito, arquivo: Path, repeticao: str) -> None:
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if "erro" in dados:
        resumo.falhas += 1
        return
    resultado = ResultadoExtracao.model_validate(dados)
    contagem, problemas = comparar(gabarito, resultado)
    resumo.contagem += contagem
    if contagem.acuracia_preco is not None:
        resumo.acuracias.append(contagem.acuracia_preco)
    resumo.tempos.append(resultado.metricas.tempo_s)
    resumo.custos.append(resultado.metricas.custo_estimado_usd)
    resumo.problemas += [f"{gabarito.cardapio} (execução {repeticao}) — {p}" for p in problemas]
    if gabarito.itens == [] and contagem.extraidos:
        resumo.problemas.append(
            f"{gabarito.cardapio} (execução {repeticao}) — {contagem.extraidos} itens inventados"
        )


def _relatorio(
    execucao: dict[str, object],
    gabaritos: dict[str, Gabarito],
    resumos: dict[str, dict[str, Resumo]],
) -> str:
    modelos = list(resumos)
    cardapios = sorted({c for por_cardapio in resumos.values() for c in por_cardapio})
    linhas = [
        "## Resultado da avaliação",
        "",
        f"{execucao['data']} · {len(cardapios)} cardápios · "
        f"{execucao['repeticoes']} repetição(ões) "
        f"por modelo · limiar de revisão {execucao['limiar_confianca']}",
        "",
        "| Modelo | Recall de itens | Precisão de itens | Preço correto | Itens em revisão "
        "| Preço errado sem aviso | Ilegível com preço e sem aviso | Tempo médio | Custo médio "
        "| Falhas |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for modelo in modelos:
        linhas.append(_linha_do_modelo(modelo, list(resumos[modelo].values())))
    linhas += [
        "",
        "### Preço correto por cardápio",
        "",
        "Média entre as repetições (mínimo–máximo).",
        "",
    ]
    linhas.append("| Cardápio | Gabarito | Itens | " + " | ".join(modelos) + " |")
    linhas.append("|---|---|---|" + "---|" * len(modelos))
    for cardapio in cardapios:
        celulas = [_celula_cardapio(gabaritos[cardapio], resumos[m].get(cardapio)) for m in modelos]
        gabarito = gabaritos[cardapio]
        linhas.append(
            f"| {cardapio} | {gabarito.tipo} | {len(gabarito.itens)} | "
            + " | ".join(celulas)
            + " |"
        )
    linhas += ["", _LEGENDA]
    return "\n".join(linhas) + "\n"


_LEGENDA = (
    "**Como ler.** *Recall*: itens do gabarito que foram extraídos. *Precisão*: itens extraídos "
    "que existem no gabarito (nas fotos sem cardápio, qualquer item é invenção). *Preço correto*: "
    "preço igual ao do gabarito, entre os itens legíveis encontrados. *Preço errado sem aviso*: o "
    "erro mais grave, porque nada avisa o dono. *Ilegível com preço e sem aviso*: o modelo deu um "
    "preço a um item que não dá para ler, e o item não foi para revisão. Os itens são casados pelo "
    "nome, com tolerância a pequenas diferenças, e o preço conta como certo quando o conjunto de "
    "preços do item (preço e variações) é o do gabarito (`evals/metricas.py`). *Gabarito*: "
    '"exato" foi gerado com a imagem; "lido à mão", conferido em ampliações; "conferido a olho" '
    "partiu de uma extração do `gemini-3.5-flash-lite` corrigida pela imagem, o que pode favorecer "
    "esse modelo no casamento de nomes."
)


def _linha_do_modelo(modelo: str, resumos: Sequence[Resumo]) -> str:
    total = sum((r.contagem for r in resumos), Contagem())
    tempos = [t for r in resumos for t in r.tempos]
    custos = [c for r in resumos for c in r.custos]
    falhas = sum(r.falhas for r in resumos)
    execucoes = len(tempos) + falhas
    return (
        f"| {modelo} "
        f"| {_porcento(total.recall)} ({total.casados}/{total.esperados}) "
        f"| {_porcento(total.precisao)} ({total.casados}/{total.extraidos}) "
        f"| {_porcento(total.acuracia_preco)} ({total.precos_corretos}/{total.precos_avaliados}) "
        f"| {_porcento(total.taxa_revisao)} "
        f"| {total.erros_sem_aviso} "
        f"| {total.ilegiveis_com_preco_sem_aviso} de {total.ilegiveis} "
        f"| {_media_tempo(tempos)} "
        f"| {_media_custo(custos)} "
        f"| {falhas}/{execucoes} |"
    )


def _celula_cardapio(gabarito: Gabarito, resumo: Resumo | None) -> str:
    if resumo is None:
        return "—"
    if not gabarito.itens:
        execucoes = len(resumo.tempos)
        inventados = resumo.contagem.extraidos
        return f"{inventados} itens inventados em {execucoes} execução(ões)"
    if not resumo.acuracias:
        return f"falhou {resumo.falhas}x"
    media = statistics.mean(resumo.acuracias)
    faixa = f"{_porcento(min(resumo.acuracias))}–{_porcento(max(resumo.acuracias))}"
    falhas = f", {resumo.falhas} falha(s)" if resumo.falhas else ""
    return f"{_porcento(media)} ({faixa}{falhas})"


def _detalhes(resumos: dict[str, dict[str, Resumo]]) -> str:
    linhas = ["## Problemas de preço por modelo", ""]
    for modelo, por_cardapio in resumos.items():
        linhas += [f"### {modelo}", ""]
        problemas = [p for r in por_cardapio.values() for p in r.problemas]
        linhas += [f"- {p}" for p in problemas] or ["Nenhum."]
        linhas.append("")
    return "\n".join(linhas)


def _porcento(valor: float | None) -> str:
    return "—" if valor is None else f"{valor * 100:.1f}%".replace(".", ",")


def _media_tempo(tempos: Sequence[float]) -> str:
    return "—" if not tempos else f"{statistics.mean(tempos):.1f} s".replace(".", ",")


def _media_custo(custos: Sequence[Decimal | None]) -> str:
    if not custos or any(custo is None for custo in custos):
        return "não cadastrado"
    media = sum((c for c in custos if c is not None), Decimal(0)) / len(custos)
    return f"US$ {media:.4f}".replace(".", ",")


if __name__ == "__main__":
    sys.exit(main())
