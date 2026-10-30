# Cardápio Instantâneo

Transforma fotos de um cardápio físico em um cardápio digital estruturado (JSON), usando um LLM multimodal.
O sistema nunca inventa preço: itens com preço ilegível ou baixa confiança vão para revisão humana.

> **Status:** Fases 1 e 2 concluídas. Fase 3 (várias fotos, descrições sugeridas e painel) no
> branch `fase-3`, aguardando revisão. Avaliação e deploy chegam nas próximas fases.

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
git switch fase-3             # branch da fase em andamento
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

## Testes

```bash
python -m pytest            # testes offline (sem chamar API)
python -m pytest -m live    # teste com a API real (requer chave; gera custo)
ruff check . && mypy core tests evals app streamlit_app.py
```

Decisões técnicas: [docs/decisoes.md](docs/decisoes.md).
