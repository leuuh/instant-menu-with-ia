# Briefing do projeto

Projeto de portfólio para uma vaga de estágio em IA, feito em fases, com revisão ao fim de cada uma.

## O produto
Donos de restaurantes pequenos levam horas para cadastrar o cardápio em apps de delivery. O Cardápio Instantâneo recebe uma ou mais fotos (ou PDF) de um cardápio físico e devolve, em menos de 1 minuto, um cardápio digital estruturado, editável e exportável.

## Funcionalidades do MVP
1. Upload de 1 a 5 imagens (JPG/PNG) ou 1 PDF.
2. Extração via LLM multimodal para um JSON validado com Pydantic: categorias, itens, preço, descrição original, variações/tamanhos, adicionais, possíveis alergênicos e score de confiança por item.
3. Itens com confiança baixa ou preço ilegível ficam destacados para revisão humana. O sistema NUNCA inventa preço.
4. Botão para gerar descrições sugeridas mais atrativas, mantendo a original ao lado para o dono escolher.
5. Tabela editável na interface antes de exportar.
6. Exportação em JSON e CSV.
7. Painel com tempo de processamento e custo estimado por cardápio.

## Stack
- Python 3.11+, Pydantic v2, Streamlit.
- LLM com o provedor isolado numa camada própria, para trocar de modelo com uma linha de configuração.
- Chave de API em `.env` (nunca no código), com `.env.example` no repositório.
- pytest para testes, GitHub Actions para CI.
- Deploy: Streamlit Community Cloud ou Hugging Face Spaces.

## Regras técnicas
- Se o JSON do LLM falhar na validação, refazer a chamada até 2 vezes enviando o erro de volta ao modelo.
- Preços como número decimal em reais; preço ilegível = null, nunca 0.
- Cardápios com várias fotos: unir resultados e remover itens duplicados.
- Registrar em log: modelo usado, tokens, custo estimado e tempo.
- Código limpo, tipado, com docstrings curtas e funções pequenas.
- Não usar marca, logo ou dados de nenhuma empresa real de delivery.

## Avaliação (evals)
O script `evals/run_evals.py` compara a saída com os gabaritos e calcula:
- Recall e precisão de itens (casamento por nome com tolerância a pequenas diferenças).
- Acurácia de preço (preço exatamente igual ao gabarito).
- Taxa de itens enviados para revisão humana.
- Tempo e custo médio por cardápio.

Gera uma tabela em markdown para colar no README e permite comparar 2 ou mais modelos lado a lado.

## Fases
| Fase | Escopo | Estado |
|---|---|---|
| 1 | Schema Pydantic, camada de provedor e extração de uma imagem pela linha de comando, com testes | Concluída |
| 2 | Interface Streamlit com upload, tabela editável e exportação | Concluída |
| 3 | Descrições sugeridas, múltiplas imagens e painel de custo/tempo | Implementada no branch `fase-3`, aguardando revisão |
| 4 | Script de avaliação e comparação entre modelos | A fazer |
| 5 | CI, deploy e README com problema, demo, resultados, arquitetura, decisões técnicas e instruções de instalação | A fazer |

As decisões tomadas, os resultados medidos e as limitações conhecidas estão em [decisoes.md](decisoes.md).
