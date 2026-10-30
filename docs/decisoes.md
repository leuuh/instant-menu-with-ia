# Decisões técnicas

Registro das decisões do projeto, com o motivo de cada uma. A mais recente fica no fim.

## Fase 1 — schema, provedor e extração (out/2026)

### 1. Provedor padrão: Google Gemini, modelo `gemini-3.8-flash`
- Segundo a documentação oficial (consultada em 29/10/2026), é estável e "recomendado para novos projetos".
- Preço por milhão de tokens:
  - até 31/12/2026: US$ 0,75 de entrada / US$ 3,75 de saída;
  - a partir de 01/01/2027: US$ 1,50 / US$ 7,50.
- Tem free tier, o que permite desenvolver sem custo.
- **Atenção:** no free tier, o Google pode usar o conteúdo enviado para melhorar seus produtos. Fotos de cardápio são informação pública, mas não envie nada sensível nesse modo.
- Alternativa mais barata para comparar na Fase 4: `gemini-3.5-flash-lite` (US$ 0,30 / US$ 2,50).
- **Uso temporário (30/10/2026):** o `gemini-3.8-flash` estava respondendo 503 por sobrecarga, então o `.env` local usa `LLM_MODEL=gemini-3.5-flash-lite`. O padrão no código não mudou; a escolha definitiva sai dos evals da Fase 4.

### 2. Provedor isolado em `core/providers/`
- Cada provedor implementa `ProvedorLLM.gerar_json` e recebe mídias, instruções, JSON Schema e correções.
- Validação, novas tentativas, custo e log ficam fora do provedor, em `core/extract.py`. Assim, trocar de modelo não muda as regras do produto.
- Para trocar de provedor basta mudar `LLM_PROVIDER` no `.env`. `LLM_MODEL` é opcional.
- O `ProvedorFake` só existe para os testes e não aparece no registro de provedores.

### 3. API `models.generate_content` do SDK `google-genai`
- A documentação nova do Gemini mostra a Interactions API (`client.interactions.create`).
- `generate_content` continua no SDK sem aviso de descontinuação. Ela é tipada e tem os parâmetros de saída estruturada (`response_mime_type` e `response_json_schema`) e de contagem de tokens (`usage_metadata`) de que precisamos.

### 4. Saída estruturada nativa + Pydantic + até 2 correções
- O JSON Schema gerado a partir do Pydantic vai para o modo de saída estruturada do provedor. Isso praticamente elimina JSON quebrado.
- O Pydantic valida de novo localmente, porque o Gemini ignora parte do JSON Schema, como `minLength`.
- **Disparam correção** (o erro volta ao modelo, até 2 vezes): JSON fora do schema, campo extra, nome vazio, preço ≤ 0, preço com mais de 2 casas e confiança fora de [0, 1].
- **Só marcam revisão humana:** confiança abaixo de 0.7 e preços ausentes. Isso não é erro do modelo; é incerteza legítima.
- Se as 3 tentativas falharem, a extração termina com erro e registra as métricas no log. Não há resultado parcial.

### 5. Schema adaptado para o Gemini
- `schema_para_llm` coloca as definições `$ref`/`$defs` diretamente no lugar e transforma `anyOf [X, null]` em `type: [X, "null"]`.
- O motivo é que a documentação do Gemini não garante suporte a `$defs`.

### 6. Preços em `Decimal`
- `32.90` continua exatamente `32.90`: sem erro de ponto flutuante, e a métrica "preço igual ao gabarito" dos evals fica exata.
- No JSON exportado, o preço sai como número.
- Preço 0 é proibido. Preço ilegível ou ausente é `null`.

### 7. Item com variações tem `preco = null`
- Os preços ficam só em `variacoes`. O item vai para revisão por falta de preço apenas quando nenhuma variação tem preço.
- O prompt (`prompts/extracao.md`, regras 2 e 4) foi ajustado para deixar isso explícito e proibir o uso de 0.

### 8. Preparo da imagem
- O formato é validado pelo conteúdo do arquivo, não pela extensão.
- A rotação EXIF é corrigida e a transparência vira fundo branco.
- O lado maior é reduzido para no máximo 3072 px, o limite de processamento do Gemini, e a imagem é regravada como JPEG com qualidade 90.

### 9. Custo e log
- O custo é estimado em USD a partir de `core/precos.py`, uma tabela com datas de vigência e a fonte de cada preço.
- Para um modelo fora da tabela, o custo é `None`. A extração continua normalmente.
- Os tokens de raciocínio são somados aos de saída, porque são cobrados como saída.
- Cada extração gera uma linha em `logs/extracoes.jsonl` com origem, provedor, modelo, `prompt_sha`, tokens, custo, tempo, tentativas, número de itens, número em revisão e erro.
- O `prompt_sha` (8 caracteres do sha256 do prompt) identifica a versão do prompt usada em cada execução.

### 10. Ambiente Python
- O código é compatível com Python 3.11+. ruff e mypy estão configurados para 3.11.
- O venv local usa Python 3.14, porque o 3.12 listado na máquina não existia mais no disco.
- A versão de Python do deploy será fixada na Fase 5.

### 11. Limite de espera e erros de rede no provedor
- No primeiro teste real (30/10/2026), o `gemini-3.8-flash` estava sobrecarregado e a chamada ficou presa por mais de 9 minutos, porque não havia timeout.
- Agora cada tentativa tem limite de 120 s, com até 3 tentativas pelo SDK. O limite é folgado para não cortar cardápios grandes, que geram muitos tokens numa resposta sem streaming.
- Erros de rede e timeouts viram `ProvedorErro`, então a CLI mostra uma mensagem clara e a falha fica no log, em vez de um traceback.

### 12. Foto simulada para testes
- `evals/gerar_cardapio_simulado.py` desenha um cardápio fictício com problemas de foto (inclinação, sombra, reflexo, desfoque, ruído e rotação EXIF) e três armadilhas de preço: mancha, dobra no papel e preço riscado com o novo escrito à mão.
- A imagem é desenhada com Pillow, e não criada por um gerador de imagens, para que o texto seja conhecido e o gabarito (`evals/data/cardapio_simulado_01.json`) seja exato.
- **Limitação:** não substitui fotos reais. Os resultados dessa imagem não devem ser apresentados como desempenho em fotos reais.

## Fase 2 — interface, tabela editável e exportação (out/2026)

### 13. Adicionais de uma seção inteira são repetidos em cada item
- Uma nota solta ao fim de uma seção, como "Borda recheada + R$ 8,00", vale para todos os itens dela. A regra está em `prompts/extracao.md`.
- O schema não mudou, e o JSON e o CSV continuam simples. A alternativa seria um campo `adicionais` na categoria, mais fiel ao cardápio, mas que complicaria o schema e a tabela.
- **Risco aceito:** uma nota que valha só para parte da seção também será repetida em todos os itens. O dono pode corrigir na tabela.

### 14. Conexão derrubada é repetida pelo provedor
- O SDK repete erros 429/5xx, timeouts e falhas ao conectar, mas não uma conexão derrubada no meio da resposta (`ReadError`). Isso aconteceu duas vezes nos testes reais.
- `core/providers/gemini.py` agora repete esse caso até 3 vezes, com uma pausa curta.

### 15. Tabela com uma linha por item
- Variações e adicionais ficam em texto editável (`P: 18,00; G: ?`), onde `?` indica preço desconhecido. Assim o dono vê o cardápio inteiro sem tabelas aninhadas.
- Um texto fora do formato não é adivinhado: a exportação fica bloqueada e a mensagem aponta a linha e o item.

### 16. Alerta da IA fixo e pendências calculadas ao vivo
- A coluna "Alerta da IA" mostra o que o modelo sinalizou e não muda com as edições. Atualizá-la recriaria a tabela a cada edição e faria o dono perder a posição.
- O aviso acima da tabela é recalculado a cada edição. Um item sai da lista quando o motivo é resolvido ou quando o dono marca **Conferido**.
- **Conferido** nunca altera dados: um item conferido sem preço continua com `preco = null`.
- O Streamlit só colore colunas somente leitura, por isso o destaque amarelo aparece nas colunas Alerta, Confiança e Observação.

### 17. CSV para o Excel em português
- Separador `;`, vírgula decimal e BOM UTF-8, para abrir direto no Excel com acentos e números corretos. Uma importação automática em outro sistema pode precisar de ajuste.
- Uma linha por preço: item com variações gera uma linha para cada uma. Preço desconhecido fica vazio, nunca 0.
- Textos que começam com `=`, `+`, `-` ou `@` recebem `'` na frente, para o Excel não os executar como fórmula. O próprio prompt cita "+ bacon" como exemplo real.

### 18. Exportar com pendências é permitido
- O dono pode querer o arquivo antes de terminar a revisão. Os itens pendentes ficam marcados no JSON e no CSV, e há um aviso na tela.

### 19. PDF enviado direto ao modelo
- O Gemini lê PDF nativamente, então não há conversão para imagem. O limite é de 50 MB, o mesmo do Gemini, configurado também no upload do Streamlit.
- A prévia ao lado da tabela só aparece para imagens; para PDF, a tela mostra apenas o nome do arquivo.

### 20. Teste com cardápios reais (30/10/2026)
Rodei o `gemini-3.5-flash-lite` em 3 PDFs de restaurantes e 8 fotos da Wikimedia Commons (6 são cardápios; 2 são fachada e salão, e devolveram 0 itens, como deveriam). Os arquivos não estão no repositório. As fotos têm licença livre e podem virar dados de avaliação na Fase 4.

Duas fotos difíceis tiveram gabarito lido à mão, a partir de ampliações da imagem original. A Belchers tem 43 preços legíveis e um painel desbotado com 12 ilegíveis; a Tivoli é uma lousa com 34 preços. Preços legíveis corretos:

| Configuração | Belchers (43) | Tivoli (34) |
|---|---|---|
| Resolução padrão (1 execução) | 34 | 32 |
| Resolução máxima (6 execuções) | 32 a 42 | 33 a 34 |

### 21. Imagens enviadas na resolução máxima
- A resolução padrão fazia o modelo errar preços com confiança alta. A máxima (`MEDIA_RESOLUTION_ULTRA_HIGH`) melhorou a leitura e acrescentou cerca de 1.100 tokens de entrada por imagem (menos de US$ 0,001 no `flash-lite`).
- PDF fica na resolução padrão.
- Só testei a resolução máxima no `gemini-3.5-flash-lite`. Ao trocar de modelo, é preciso confirmar se ele aceita essa opção.

### 22. Limite de revisão de 0,9
- Com o limite de 0,7, itens com "preço parcialmente borrado" e confiança 0,7 ou 0,8 escapavam da revisão.
- Nas 6 execuções com o prompt atual e a resolução máxima, os itens do painel desbotado ficaram em 0,8 a 0,85, e só 3 de 230 legíveis ficaram abaixo de 0,9. Esse painel apareceu em apenas 1 das 3 execuções da Belchers, então a amostra é pequena.
- Custo: mais itens para o dono conferir. Pode ser ajustado em `LIMIAR_CONFIANCA`.

### 23. Regras de prompt testadas e descartadas
Testei regras para exigir `null` quando faltasse qualquer dígito, limitar a confiança a 0,5 em leitura duvidosa e associar nomes e preços linha por linha. Em 12 execuções comparadas (3 de cada prompt nas 2 fotos), não houve melhora mensurável e o modelo não devolveu `null` para nenhum item do painel desbotado. Além disso, a confiança ficou menos útil para separar os casos ruins, por isso voltei ao texto anterior.

### Limitações conhecidas (cardápios reais)
- **"NUNCA inventa preço" ainda não está garantido.** Em foto muito desbotada, o modelo devolve um número mesmo sem conseguir ler. O limite de 0,9 só avisa quando a confiança vem baixa. Com o prompt atual, ela veio baixa na única execução medida em que o painel desbotado apareceu inteiro, mas não há garantia de que isso se repita: com as regras descartadas, chegou a 1,0.
- **Preços trocados de linha.** Em colunas inclinadas ou curvas, o modelo às vezes pula um preço e desloca os seguintes: isso ocorreu em 2 de 6 execuções da Belchers, com 8 a 10 preços errados e confiança alta. O limite de revisão não pega esse erro.
- **Painel inteiro omitido.** Em 3 de 6 execuções da Belchers, o painel desbotado sumiu do resultado, sem aviso.
- **Moeda.** O schema guarda só o número. Um cardápio em libras ou euros não é convertido nem identificado.
- **Tempo.** Um PDF de 16 páginas e 147 itens levou 64 s, acima da meta de 1 minuto.

### Pendências para a Fase 4 (evals)
- Medir os casos acima com fotos reais em vários modelos, na resolução máxima. O `gemini-3.8-flash` respondeu 503/504 em todas as tentativas de 30/10/2026, e a chave atual não tem cota para o `gemini-4-argon`.
- Avaliar uma segunda leitura independente que marque para revisão os preços que divergirem. Nos testes, os preços inventados mudavam entre execuções.
- Medir o efeito de `media_resolution` e do nível de raciocínio na acurácia de preço e no custo. Hoje os dois usam o padrão do modelo.
- Comparar `gemini-3.8-flash` com `gemini-3.5-flash-lite` e com outros provedores.
- Adicionais que valem para uma categoria inteira ("Adicionais: bacon R$ 4,00"): na foto simulada, o `gemini-3.5-flash-lite` os colocou só no último item da categoria. Falta definir a regra.
- Ao adicionar um provedor cujo SDK instale `httpx2` (como `anthropic` 1.x), conferir se o `google-genai` passa a usá-lo e tratar também `httpx2.HTTPError` em `core/providers/gemini.py`.
