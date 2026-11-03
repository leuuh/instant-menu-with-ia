## Resultado da avaliação

2026-11-03T15:04 · 9 cardápios · 3 repetição(ões) por modelo · limiar de revisão 0.9

| Modelo | Recall de itens | Precisão de itens | Preço correto | Itens em revisão | Preço errado sem aviso | Ilegível com preço e sem aviso | Tempo médio | Custo médio | Falhas |
|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 98,7% (607/615) | 99,0% (607/613) | 100,0% (569/569) | 6,9% | 0 | 5 de 38 | 22,9 s | US$ 0,0069 | 0/27 |
| gemini-3.6-flash | 92,7% (241/260) | 95,6% (241/252) | 100,0% (232/232) | 7,9% | 0 | 1 de 9 | 35,5 s | US$ 0,0149 | 14/27 |

### Preço correto por cardápio

Média entre as repetições (mínimo–máximo).

| Cardápio | Gabarito | Itens | gemini-3.5-flash-lite | gemini-3.6-flash |
|---|---|---|---|---|
| belchers | lido à mão | 55 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 1 falha(s)) |
| fachada | sem cardápio | 0 | 0 itens inventados em 3 execução(ões) | 0 itens inventados em 3 execução(ões) |
| fatto | conferido a olho | 13 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 2 falha(s)) |
| kenya | conferido a olho | 73 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 2 falha(s)) |
| lyon | conferido a olho | 12 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 2 falha(s)) |
| salao | sem cardápio | 0 | 0 itens inventados em 3 execução(ões) | 0 itens inventados em 2 execução(ões) |
| simulado_01 | exato | 11 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 2 falha(s)) |
| tivoli | lido à mão | 34 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 2 falha(s)) |
| unithai | conferido a olho | 7 | 100,0% (100,0%–100,0%) | 100,0% (100,0%–100,0%, 2 falha(s)) |

**Como ler.** *Recall*: itens do gabarito que foram extraídos. *Precisão*: itens extraídos que existem no gabarito (nas fotos sem cardápio, qualquer item é invenção). *Preço correto*: preço igual ao do gabarito, entre os itens legíveis encontrados. *Preço errado sem aviso*: o erro mais grave, porque nada avisa o dono. *Ilegível com preço e sem aviso*: o modelo deu um preço a um item que não dá para ler, e o item não foi para revisão. Os itens são casados pelo nome, com tolerância a pequenas diferenças, e o preço conta como certo quando o conjunto de preços do item (preço e variações) é o do gabarito (`evals/metricas.py`). *Gabarito*: "exato" foi gerado com a imagem; "lido à mão", conferido em ampliações; "conferido a olho" partiu de uma extração do `gemini-3.5-flash-lite` corrigida pela imagem, o que pode favorecer esse modelo no casamento de nomes.
