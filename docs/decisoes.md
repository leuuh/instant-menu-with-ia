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

### Pendências para a Fase 4 (evals)
- Medir o efeito de `media_resolution` e do nível de raciocínio na acurácia de preço e no custo. Hoje os dois usam o padrão do modelo.
- Comparar `gemini-3.8-flash` com `gemini-3.5-flash-lite` e com outros provedores.
- Adicionais que valem para uma categoria inteira ("Adicionais: bacon R$ 4,00"): na foto simulada, o `gemini-3.5-flash-lite` os colocou só no último item da categoria. Falta definir a regra.
- Ao adicionar um provedor cujo SDK instale `httpx2` (como `anthropic` 1.x), conferir se o `google-genai` passa a usá-lo e tratar também `httpx2.HTTPError` em `core/providers/gemini.py`.
