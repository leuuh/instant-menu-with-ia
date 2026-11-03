"""Compara uma extração com o gabarito: casamento de itens por nome e contagens."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from core.edicao import formatar_preco
from core.schema import ItemExtraido, ResultadoExtracao
from core.unir import normalizar

LIMIAR_NOME = 0.8
SEMELHANCA_PREFIXO = 0.85  # "Nems" casa com "Nems porc ou poulet"
PESO_CATEGORIA = 0.3  # só desempata: "Bacon" existe em mais de uma seção


@dataclass(frozen=True)
class ItemGabarito:
    categoria: str
    nome: str
    preco: Decimal | None
    variacoes: tuple[Decimal | None, ...]
    ilegivel: bool  # o preço não pode ser lido: o certo é null ou ir para revisão


@dataclass(frozen=True)
class Gabarito:
    cardapio: str
    tipo: str  # exato, lido à mão, conferido a olho ou sem cardápio
    arquivo: str  # caminho no repositório ou URL da Wikimedia Commons
    licenca: str
    conferencia: str
    itens: list[ItemGabarito]


@dataclass(frozen=True)
class ItemObtido:
    categoria: str
    item: ItemExtraido
    em_revisao: bool


@dataclass
class Contagem:
    """Contagens somáveis entre execuções; as taxas saem delas, não de médias de médias."""

    esperados: int = 0
    extraidos: int = 0
    casados: int = 0
    precos_avaliados: int = 0
    precos_corretos: int = 0
    em_revisao: int = 0
    erros_sem_aviso: int = 0
    ilegiveis: int = 0
    ilegiveis_com_preco_sem_aviso: int = 0

    def __add__(self, outra: "Contagem") -> "Contagem":
        return Contagem(
            **{c.name: getattr(self, c.name) + getattr(outra, c.name) for c in fields(self)}
        )

    @property
    def recall(self) -> float | None:
        return _taxa(self.casados, self.esperados)

    @property
    def precisao(self) -> float | None:
        return _taxa(self.casados, self.extraidos)

    @property
    def acuracia_preco(self) -> float | None:
        return _taxa(self.precos_corretos, self.precos_avaliados)

    @property
    def taxa_revisao(self) -> float | None:
        return _taxa(self.em_revisao, self.extraidos)


def carregar_gabarito(caminho: Path) -> Gabarito:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return Gabarito(
        cardapio=dados["cardapio"],
        tipo=dados["tipo"],
        arquivo=dados["arquivo"],
        licenca=dados["licenca"],
        conferencia=dados["conferencia"],
        itens=[_item_gabarito(item) for item in dados["itens"]],
    )


def itens_obtidos(resultado: ResultadoExtracao) -> list[ItemObtido]:
    revisao = {(r.categoria, r.indice_item) for r in resultado.revisao}
    return [
        ItemObtido(categoria.nome, item, (categoria.nome, indice) in revisao)
        for categoria in resultado.cardapio.categorias
        for indice, item in enumerate(categoria.itens)
    ]


def similaridade(a: str, b: str) -> float:
    """1 para nomes iguais após normalizar; prefixo de palavras inteiras vale 0,85."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    curto, longo = sorted((na, nb), key=len)
    razao = SequenceMatcher(None, na, nb).ratio()
    if f"{longo} ".startswith(f"{curto} "):
        razao = max(razao, SEMELHANCA_PREFIXO)
    return razao


def casar(
    esperados: Sequence[ItemGabarito], obtidos: Sequence[ItemObtido]
) -> list[tuple[int, int]]:
    """Pares (esperado, obtido): cada item casa no máximo uma vez, os mais parecidos primeiro."""
    candidatos = []
    for i, esperado in enumerate(esperados):
        for j, obtido in enumerate(obtidos):
            nome = similaridade(esperado.nome, obtido.item.nome)
            if nome >= LIMIAR_NOME:
                categoria = similaridade(esperado.categoria, obtido.categoria)
                candidatos.append((nome + PESO_CATEGORIA * categoria, i, j))
    candidatos.sort(key=lambda candidato: (-candidato[0], candidato[1], candidato[2]))
    usados_esperados: set[int] = set()
    usados_obtidos: set[int] = set()
    pares: list[tuple[int, int]] = []
    for _, i, j in candidatos:
        if i not in usados_esperados and j not in usados_obtidos:
            pares.append((i, j))
            usados_esperados.add(i)
            usados_obtidos.add(j)
    return sorted(pares)


def comparar(gabarito: Gabarito, resultado: ResultadoExtracao) -> tuple[Contagem, list[str]]:
    """Contagens da execução e a descrição de cada problema de preço, para o relatório."""
    obtidos = itens_obtidos(resultado)
    pares = casar(gabarito.itens, obtidos)
    contagem = Contagem(
        esperados=len(gabarito.itens),
        extraidos=len(obtidos),
        casados=len(pares),
        em_revisao=sum(obtido.em_revisao for obtido in obtidos),
    )
    problemas: list[str] = []
    for i, j in pares:
        problema = _avaliar_preco(gabarito.itens[i], obtidos[j], contagem)
        if problema:
            problemas.append(problema)
    return contagem, problemas


def _avaliar_preco(esperado: ItemGabarito, obtido: ItemObtido, contagem: Contagem) -> str | None:
    if esperado.ilegivel:
        contagem.ilegiveis += 1
        if _tem_preco(obtido.item) and not obtido.em_revisao:
            contagem.ilegiveis_com_preco_sem_aviso += 1
            return f"{esperado.nome}: ilegível, extraído {_descrever(obtido.item)} sem aviso"
        return None
    contagem.precos_avaliados += 1
    if _preco_correto(esperado, obtido.item):
        contagem.precos_corretos += 1
        return None
    aviso = "com aviso" if obtido.em_revisao else "sem aviso"
    if not obtido.em_revisao:
        contagem.erros_sem_aviso += 1
    esperado_texto, obtido_texto = _descrever_esperado(esperado), _descrever(obtido.item)
    return f"{esperado.nome}: esperado {esperado_texto}, extraído {obtido_texto} ({aviso})"


def _preco_correto(esperado: ItemGabarito, item: ItemExtraido) -> bool:
    """Mesmos preços, como quer que estejam organizados.

    "3,80 e meia porção 1,90" pode vir como preço do item mais uma variação ou como duas
    variações: os dois jeitos estão certos. Não confere qual preço foi para qual variação.
    """
    obtidos = [item.preco, *(v.preco for v in item.variacoes)]
    return _ordenar(obtidos) == _ordenar([esperado.preco, *esperado.variacoes])


def _tem_preco(item: ItemExtraido) -> bool:
    return item.preco is not None or any(v.preco is not None for v in item.variacoes)


def _ordenar(precos: Any) -> list[Decimal]:
    return sorted(preco for preco in precos if preco is not None)


def _descrever(item: ItemExtraido) -> str:
    variacoes = [_texto_preco(v.preco) for v in item.variacoes]
    return _texto_preco(item.preco) + (f" [{'; '.join(variacoes)}]" if variacoes else "")


def _descrever_esperado(esperado: ItemGabarito) -> str:
    variacoes = [_texto_preco(p) for p in esperado.variacoes]
    return _texto_preco(esperado.preco) + (f" [{'; '.join(variacoes)}]" if variacoes else "")


def _texto_preco(preco: Decimal | None) -> str:
    return formatar_preco(preco) if preco is not None else "null"


def _item_gabarito(dados: dict[str, Any]) -> ItemGabarito:
    return ItemGabarito(
        categoria=dados["categoria"],
        nome=dados["nome"],
        preco=_decimal(dados["preco"]),
        variacoes=tuple(_decimal(v["preco"]) for v in dados["variacoes"]),
        ilegivel=bool(dados["ilegivel"]),
    )


def _decimal(valor: float | None) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def _taxa(parte: int, total: int) -> float | None:
    return parte / total if total else None
