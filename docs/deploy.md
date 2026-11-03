# Deploy no Streamlit Community Cloud

O deploy exige o seu login no Streamlit, então é feito por você. Leva uns 5 minutos.

## Antes de começar
- A versão a publicar precisa estar na branch `main` do GitHub.
- Tenha em mãos a chave do Gemini e uma senha para a versão pública.

## Passo a passo
1. Entre em [share.streamlit.io](https://share.streamlit.io) com a conta do GitHub.
2. Clique em **Create app** e escolha publicar a partir de um repositório do GitHub.
3. Preencha:
    - **Repository:** `leuuh/instant-menu-with-ia`
    - **Branch:** `main`
    - **Main file path:** `streamlit_app.py`
4. Em **Advanced settings**:
    - **Python version:** 3.13, a mais nova testada no CI.
    - **Secrets:** cole o bloco abaixo, trocando os valores.

    ```toml
    GEMINI_API_KEY = "sua-chave-do-gemini"
    LLM_MODEL = "gemini-3.5-flash-lite"
    LLM_MODEL_DESCRICOES = "gemini-3.6-flash"
    SENHA_ACESSO = "uma-senha-para-a-demo"
    MAX_USOS_IA_POR_DIA = "100"
    ```

5. Clique em **Deploy**. A primeira instalação demora alguns minutos.

O Streamlit transforma os secrets do nível raiz em variáveis de ambiente, e a configuração do app
(`core/config.py`) lê essas variáveis. Por isso nenhum arquivo `.env` vai para o servidor.

## Proteções da versão pública
- **Sem `SENHA_ACESSO`, qualquer visitante usa a sua chave.** Com a senha, quem não a tem só consegue abrir o exemplo pronto, que não chama a IA.
- **`MAX_USOS_IA_POR_DIA`:** limita extrações e descrições somando todos os visitantes. O contador fica na memória do servidor e recomeça se o app reiniciar.
- **Free tier do Gemini:** o Google pode usar o conteúdo enviado para melhorar os produtos dele. Avise isso a quem for testar com fotos próprias.

## Depois do deploy
- Coloque o link público na seção **Demo** do README.
- Para atualizar o app, basta fazer push na `main`: o Streamlit Cloud publica sozinho.
