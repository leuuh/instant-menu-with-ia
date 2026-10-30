# Cardápio Instantâneo

Leia `docs/projeto.md` (briefing e fases) e `docs/decisoes.md` (decisões, medições e limitações) antes de propor mudanças.

## Como trabalhar neste projeto
- Trabalhe em uma fase por vez e pare ao fim de cada uma para revisão.
- Faça commit e push só quando pedirem. Fases em andamento ficam em um branch `fase-N`.
- Nunca coloque a chave de API no código ou no git: ela fica só no `.env`.
- Não coloque no repositório cardápios de empresas reais. Fotos reais de teste são referenciadas em `evals/data/fotos_reais.json`.
- Não afirme desempenho em fotos reais com base na imagem simulada.
- Mudança em prompt ou modelo se mede com várias execuções: os resultados variam entre execuções.

## Comandos
```bash
streamlit run streamlit_app.py
python -m core.cli extrair foto1.jpg foto2.jpg --saida cardapio.json
python -m pytest                # offline, sem chamar API
python -m pytest -m live        # API real: exige chave no .env
ruff check . && ruff format --check . && mypy core tests evals app streamlit_app.py
```
