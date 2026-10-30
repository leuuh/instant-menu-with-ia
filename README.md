# Cardápio Instantâneo

Transforma fotos de um cardápio físico em um cardápio digital estruturado (JSON), usando um LLM multimodal.
O sistema nunca inventa preço: itens com preço ilegível ou baixa confiança vão para revisão humana.

> **Status:** Fase 1 concluída (schema, camada de provedor e extração pela linha de comando).
> Interface, avaliação e deploy chegam nas próximas fases.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env        # e preencha GEMINI_API_KEY
```

## Uso

```bash
python -m core.cli extrair foto_do_cardapio.jpg --saida cardapio.json
```

A saída traz o cardápio, a lista de itens para revisão (com o motivo) e as métricas da extração
(modelo, tokens, custo estimado e tempo).

## Testes

```bash
python -m pytest            # testes offline (sem chamar API)
python -m pytest -m live    # teste com a API real (requer chave; gera custo)
ruff check . && mypy core tests
```

Decisões técnicas: [docs/decisoes.md](docs/decisoes.md).
