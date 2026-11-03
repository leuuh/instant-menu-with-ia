# Cardápio Instantâneo

Transforma fotos de um cardápio físico em um cardápio digital estruturado (JSON), usando um LLM multimodal.
O sistema nunca inventa preço: itens com preço ilegível ou baixa confiança vão para revisão humana.

> **Status:** Fases 1 a 3 concluídas. Fase 4 (avaliação e comparação de modelos) no branch
> `fase-4`, aguardando revisão. O deploy chega na Fase 5.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env        # e preencha GEMINI_API_KEY
```

## Continuar em outra máquina

```bash
git clone https://github.com/leuuh/instant-menu-with-ia.git
cd instant-menu-with-ia
git switch fase-4             # branch da fase em andamento
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env        # Linux/macOS: cp .env.example .env
```

Preencha `GEMINI_API_KEY` no `.env`: a chave não vai para o GitHub. Chave em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Para conferir, rode
`python -m pytest`.

O briefing e as fases estão em [docs/projeto.md](docs/projeto.md), e as decisões e limitações em
[docs/decisoes.md](docs/decisoes.md). As instruções para o Claude Code estão em `CLAUDE.md`.

## Uso

### Interface

```bash
streamlit run streamlit_app.py
```

Envie até 5 fotos (JPG/PNG) ou 1 PDF do cardápio, revise os itens destacados na tabela, gere
descrições sugeridas se quiser e exporte em JSON ou CSV.

### Linha de comando

```bash
python -m core.cli extrair foto1.jpg foto2.jpg --saida cardapio.json
```

A saída traz o cardápio, a lista de itens para revisão (com o motivo) e as métricas da extração
(modelo, tokens, custo estimado e tempo).

## Avaliação

```bash
python -m evals.run_evals --modelos gemini-3.5-flash-lite gemini-3.6-flash --repeticoes 3
python -m evals.run_evals --reavaliar evals/resultados/<pasta>   # só recalcula, sem API
python -m evals.run_evals --retomar evals/resultados/<pasta>     # refaz o que falhou
```

O script compara cada extração com os gabaritos de `evals/data/gabaritos/` e gera
`relatorio.md`, com uma tabela para colar aqui, e `detalhes.md`, com cada erro de preço. O
resultado mais recente está em [evals/resultados/2026-11-03_1504/relatorio.md](evals/resultados/2026-11-03_1504/relatorio.md).

## Testes

```bash
python -m pytest            # testes offline (sem chamar API)
python -m pytest -m live    # teste com a API real (requer chave; gera custo)
ruff check . && mypy core tests evals app streamlit_app.py
```

Decisões técnicas: [docs/decisoes.md](docs/decisoes.md).
