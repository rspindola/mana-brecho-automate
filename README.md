# Maná Brechó — publicação na Nuvemshop

Os scripts deste repositório pegam posts do Instagram, montam a planilha `publicacoes.csv` e criam os produtos na Nuvemshop, já com descrição, categoria, marca, tags e SEO. Os produtos nascem ocultos (rascunho): só aparecem na loja depois que você muda a visibilidade no painel.

Fluxo:

1. Baixar os posts para `downloads/`.
2. Gerar a descrição de cada peça, pelo Gemini ou pelo Cursor.
3. Revisar `publicacoes.csv` e marcar `status` como `ok`.
4. Publicar na Nuvemshop.

## Arquivos

| Arquivo                     | Para que serve                                                                                                        |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `baixar_por_url.py`         | Baixa os posts do Instagram listados em `urls.txt`                                                                    |
| `preparar_publicacao.py`    | Monta `publicacoes.csv` (título, tamanho, valor, descrição, categoria, SEO...)                                        |
| `publicar_nuvemshop.py`     | Cria na Nuvemshop os produtos aprovados na planilha                                                                   |
| `categorias_nuvemshop.py`   | Lê as categorias que já existem na loja. **Os dois scripts acima precisam dele na mesma pasta.** Nunca cria categoria |
| `exportar_dimensoes.py`     | Exporta os produtos com categoria, tamanho, peso e dimensões, e calcula as medidas médias por categoria               |
| `gerar_dimensoes_padrao.py` | Transforma o `medias_dimensoes.csv` na tabela editável `dimensoes_padrao.csv` (mediana por categoria)                 |
| `dimensoes_padrao.py`       | Consulta a tabela de medidas padrão (o `preparar_publicacao.py` precisa dele na mesma pasta)                          |
| `dimensoes_padrao.csv`      | Tabela de peso e dimensões padrão por categoria. Edite à mão o que quiser                                             |
| Scripts auxiliares          | Manutenção da loja (veja o fim deste arquivo)                                                                         |

## Requisitos

Python 3 e as bibliotecas usadas pelos scripts:

```bash
pip install instaloader requests
```

Credenciais ficam em variáveis de ambiente. Não cole tokens no código nem no git. O arquivo `.env` já está no `.gitignore`.

| Variável                 | Quando                                                                                                |
| ------------------------ | ----------------------------------------------------------------------------------------------------- |
| `GEMINI_API_KEY`         | Gerar descrições com o Gemini                                                                         |
| `ANTHROPIC_API_KEY`      | Alternativa paga (Claude), se não houver chave do Gemini                                              |
| `NUVEMSHOP_STORE_ID`     | Publicar, exportar e consultar a loja. Também faz o `preparar_publicacao.py` sugerir categorias reais |
| `NUVEMSHOP_ACCESS_TOKEN` | Idem                                                                                                  |

O token da Nuvemshop vem de um app privado em [partners.nuvemshop.com.br](https://partners.nuvemshop.com.br), com os escopos `read_products` e `write_products`. O `user_id` devolvido no OAuth é o `NUVEMSHOP_STORE_ID`. Documentação: [autenticação da API](https://tiendanube.github.io/api-documentation/authentication).

## 1. Baixar os posts

Crie `urls.txt` na raiz, com uma URL de post por linha:

```text
https://www.instagram.com/p/ABC123xyz/
https://www.instagram.com/p/DEF456uvw/
```

Baixe só esses posts (o login reduz a chance de bloqueio do Instagram):

```bash
python baixar_por_url.py urls.txt --login SEU_USUARIO
```

Na primeira vez o script pede a senha e grava a sessão. Nas seguintes, reutiliza a sessão. Cada post vira uma pasta:

```text
downloads/2024-06-01_18-30-00_ABC123/
    foto_1.jpg
    foto_2.jpg
    legenda.txt
```

Posts que já existem em `downloads/` são pulados. Vídeos e reels sem foto são ignorados. A pausa entre posts é de 8 a 15 segundos (`--delay-min` e `--delay-max`). A pasta de destino padrão é `downloads` (`--destino`).

## 2. Gerar a planilha

`preparar_publicacao.py` lê cada pasta de `downloads/`, tira da `legenda.txt` o título, o tamanho, o valor e o código da dona (entre parênteses depois do valor) e grava `publicacoes.csv`.

### Descrição

A descrição de cada pasta segue esta ordem:

1. Se existir `descricao.txt` na pasta, esse texto entra na planilha.
2. Se não existir e `GEMINI_API_KEY` estiver definida, o Gemini escreve a descrição.
3. Se não houver Gemini e `ANTHROPIC_API_KEY` estiver definida, o Claude escreve.
4. Sem arquivo e sem chave, o script usa um texto de template e marca na coluna `aviso` que a descrição é genérica.

O script acrescenta as iniciais da dona no final da descrição, entre parênteses, por exemplo `(EM)`. Por isso a IA e o `descricao.txt` **não devem escrever** as iniciais. O nome correspondente ao código está no dicionário `CLIENTES`, no início de `preparar_publicacao.py`. Código novo precisa ser incluído ali; caso contrário a coluna `aviso` indica que as iniciais não foram identificadas.

### Categoria, marca, tags e SEO

Para cada peça, o script também preenche estas colunas, sem usar IA:

| Coluna          | Como é gerada                                                                                            |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| `categoria`     | Uma categoria que **já existe** na loja (veja abaixo)                                                    |
| `marca`         | Só se o nome estiver na lista `MARCAS_CONHECIDAS` e aparecer no título ou na legenda. Nunca é adivinhada |
| `tags`          | Palavras do título, "brechó", "moda feminina", marca, categoria e tamanho (até 10)                       |
| `titulo_seo`    | Até 70 caracteres: `Título - Brechó Feminino \| Maná Brechó`                                             |
| `descricao_seo` | As primeiras frases da descrição que cabem em 160 caracteres, sem as iniciais                            |
| `url_produto`   | O título sem acentos, em minúsculas e com hífens                                                         |

**Categoria.** Com `NUVEMSHOP_STORE_ID` e `NUVEMSHOP_ACCESS_TOKEN` definidos, o script lê as categorias da loja e só sugere uma delas, incluindo subcategorias (`Roupas > Vestidos`). Ele compara o título com os nomes das categorias e, se não achar, usa a lista de sinônimos `CATEGORIAS_POR_PALAVRA` (por exemplo, "papete" leva para "Calçados", se essa categoria existir). Se nada combinar, a coluna fica vazia e o `aviso` pede para você preencher. Sem as credenciais, a coluna é apenas uma sugestão, e o `publicar_nuvemshop.py` confere com a loja antes de enviar.

### O que dá para ajustar

No início de `preparar_publicacao.py`:

| Variável                                       | O que muda                                                                                                |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `SYSTEM_PROMPT_BASE`                           | O tom e as regras da descrição (hoje: sofisticado, 500 a 800 caracteres, sem inventar material ou estado) |
| `EXEMPLOS_DESCRICOES`                          | Exemplos de estrutura que a IA recebe                                                                     |
| `MODELO_GEMINI`, `MODELOS_ALTERNATIVOS_GEMINI` | Modelo principal e os que o script tenta se o principal falhar                                            |
| `USAR_FOTOS`                                   | Padrão da IA ler as fotos. Prefira a opção `--com-fotos` quando precisar                                  |
| `NOME_LOJA`                                    | Nome que aparece no título SEO                                                                            |
| `MARCAS_CONHECIDAS`                            | Marcas que o script reconhece                                                                             |
| `CATEGORIAS_POR_PALAVRA`                       | Sinônimos para sugerir categorias                                                                         |
| `CLIENTES`                                     | Código da dona e nome                                                                                     |

### Pelo Gemini

```bash
export GEMINI_API_KEY="sua_chave"
python preparar_publicacao.py
```

Por padrão a IA recebe só o título e a legenda (mais rápido, gasta menos cota). Para enviar até 3 fotos de cada post:

```bash
python preparar_publicacao.py --com-fotos
```

Outras opções:

```bash
python preparar_publicacao.py --limite 5          # só os 5 primeiros posts, para testar
python preparar_publicacao.py --listar-modelos    # modelos Gemini disponíveis para a chave
python preparar_publicacao.py --origem downloads --saida publicacoes.csv
```

O modelo principal está em `MODELO_GEMINI` (`gemini-3.1-flash-lite`). Se ele falhar ou demorar, o script tenta `gemini-3.5-flash` e `gemini-flash-latest`, e repete a chamada em caso de erro 503 ou de limite do plano gratuito. Há uma pausa de 6 segundos entre posts. `Ctrl+C` interrompe e salva o que já foi processado.

Pastas que já têm `descricao.txt` não chamam a API, mesmo com a chave definida. Dá para misturar: o Cursor escreve um lote e o Gemini preenche o restante.

### Pelo Cursor

A regra [`.cursor/rules/descricao-produtos.mdc`](.cursor/rules/descricao-produtos.mdc) vale para arquivos em `downloads/`. Ela pede uma descrição em texto puro, UTF-8, de 500 a 800 caracteres, em três parágrafos, só com o que está na legenda ou nas fotos, e sem as iniciais da dona.

No chat do agente, com este projeto aberto:

```text
Crie descricao.txt nas pastas de downloads/ que ainda não têm o arquivo,
seguindo a regra descricao-produtos. Trabalhe em lotes de 10 e mostre
2 exemplos ao fim de cada lote.
```

O agente grava `descricao.txt` em cada pasta e não sobrescreve um arquivo que já exista. Quando o lote estiver pronto, gere a planilha. Toda pasta de `downloads/` entra no CSV: as que têm `descricao.txt` usam esse texto; as que não têm, e sem chave de API, recebem o texto de template:

```bash
python preparar_publicacao.py
```

Com `GEMINI_API_KEY` definida, as pastas sem `descricao.txt` são preenchidas pelo Gemini na mesma execução.

## 3. Revisar a planilha

Abra `publicacoes.csv`. Cada linha nasce com `status` igual a `revisar`. Confira título, tamanho, valor, descrição e a coluna `aviso`, que aponta o que precisa de atenção:

- `MÚLTIPLOS ITENS neste post`: o post tem mais de uma peça; preencha à mão.
- `Descrição por TEMPLATE (a IA falhou)`: gere de novo ou escreva a descrição.
- `Categoria não identificada`: escolha uma categoria que já exista na loja.
- `Iniciais da dona NÃO identificadas`: inclua o código em `CLIENTES` ou corrija o título.
- `Tamanho não informado — será ÚNICO`: confira se a peça realmente é de tamanho único.
- `Sem medidas padrão para a categoria`: preencha peso e dimensões à mão.
- `Medidas da categoria-mãe`: a categoria não tem linha própria na tabela; confira os valores.

Revise também `categoria`, `marca` e as medidas (`peso_kg`, `largura_cm`, `altura_cm`, `profundidade_cm`), porque são sugestões automáticas. Troque `status` para `ok` só nas linhas que devem ir para a loja. Valores aceitos como aprovado: `ok`, `sim`, `yes`, `1`, `true`.

## 4. Publicar na Nuvemshop

```bash
export NUVEMSHOP_STORE_ID="seu_user_id"
export NUVEMSHOP_ACCESS_TOKEN="seu_token"
python publicar_nuvemshop.py
```

O script publica somente as linhas com status aprovado. Para cada uma:

1. Cria o produto, com a descrição em parágrafos (`<p>`), e a variação de tamanho com estoque 1.
2. Envia as fotos na ordem do post.
3. Preenche o campo `dona_do_item` com `CÓDIGO - Nome`. O campo precisa já existir na loja como `text_list`; o script não cria um campo novo.
4. Preenche a categoria, a marca, as tags, o título SEO, a descrição SEO e a URL do produto.
5. Preenche o peso e as dimensões da variação, com os valores das colunas de medidas do CSV (colunas em branco são ignoradas).

**Categoria.** O script converte o nome da coluna `categoria` no ID de uma categoria que já existe na loja. Se o nome não existir (ou houver duas categorias com o mesmo nome), o produto é criado sem categoria e o script mostra as categorias disponíveis. Ele nunca cria categoria.

**Campos de busca e SEO.** Se a Nuvemshop recusar o formato de algum campo, o script tenta o formato alternativo e informa qual campo falhou e por quê. O produto já foi criado, então nada é perdido.

```bash
python publicar_nuvemshop.py --planilha publicacoes.csv --origem downloads
```

O log fica em `resultados_publicacao.csv`, com as colunas `categoria_id` e `campos_com_erro`. Os produtos ficam ocultos. No painel da Nuvemshop, revise cada um e mude a visibilidade para visível quando estiver pronto.

## Peso e dimensões

Na Nuvemshop, peso (kg) e dimensões (cm) ficam na **variação**, e um valor vazio ou zero conta como não preenchido.

O preenchimento automático usa uma tabela de medidas padrão por categoria:

1. `python exportar_dimensoes.py` lê a loja (somente leitura) e grava `produtos_dimensoes.csv` (uma linha por variação) e `medias_dimensoes.csv` (média e mediana por categoria). Com `--por-tamanho`, as médias saem por categoria e tamanho.
2. `python gerar_dimensoes_padrao.py` transforma as **medianas** em `dimensoes_padrao.csv`. Categorias com menos de 2 variações medidas ficam de fora (`--min-amostra` muda isso).
3. Abra `dimensoes_padrao.csv` e corrija o que quiser. A coluna `amostra` mostra em quantas peças o valor se baseia.
4. `preparar_publicacao.py` preenche `peso_kg`, `largura_cm`, `altura_cm` e `profundidade_cm` de cada linha pela categoria. Você revisa no CSV, e `publicar_nuvemshop.py` envia esses valores à variação.

Como a tabela é escolhida: primeiro a própria categoria; depois o nome curto, se for único (`Vestidos` leva a `Roupas > Vestidos`); depois a categoria-mãe, subindo um nível por vez. Se nada servir, as colunas ficam em branco e o `aviso` pede para você preencher.

Prefira a **mediana**: uma peça fora do padrão distorce a média. Quando a loja ganhar muitos produtos novos, rode os passos 1 e 2 de novo para atualizar a tabela.

## Problemas comuns

| Mensagem                             | O que fazer                                                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `404 ... models/...:generateContent` | O modelo do Gemini foi aposentado. Rode `--listar-modelos` e ajuste `MODELO_GEMINI`                           |
| `503` ou "sem resposta em 45s"       | Sobrecarga do Google. O script repete e troca de modelo; se persistir, tente em outro horário ou use o Cursor |
| `429` / limite do plano gratuito     | Aguarde, ou use `--limite` para processar em lotes menores                                                    |
| "a categoria ... não existe na loja" | Escolha na coluna `categoria` um nome da lista que o script mostra                                            |
| `campos_com_erro` preenchido no log  | A Nuvemshop recusou esse campo; copie a mensagem de erro do terminal                                          |

## Scripts auxiliares

Todos leem a loja com `NUVEMSHOP_STORE_ID` e `NUVEMSHOP_ACCESS_TOKEN`, exceto `produtos_sem_variacao.py`, que usa só `NUVEMSHOP_ACCESS_TOKEN`.

| Script                     | O que faz                                                                                   | Comando                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `produtos_sem_variacao.py` | Lista produtos sem variação (tamanho, cor) e grava `produtos_sem_variacao.csv`. Só leitura. | `python produtos_sem_variacao.py`                                  |
| `produtos-sem-dona.py`     | Lista produtos sem o campo "Dona do Item".                                                  | `python produtos-sem-dona.py`                                      |
| `migrar_campo_dona.py`     | Copia a dona do campo legado para o campo oficial e apaga o legado.                         | `python migrar_campo_dona.py`                                      |
| `trocar_marca.py`          | Troca a marca de todos os produtos de um valor para outro.                                  | `python trocar_marca.py --de "Maria Brechó" --para "DiDue Brechó"` |
| `remover_custom_field.py`  | Desassocia um campo personalizado dos produtos e depois o apaga.                            | `python remover_custom_field.py --id ID_DO_CAMPO`                  |

`migrar_campo_dona.py` e `remover_custom_field.py` alteram a loja. Confira os IDs no topo de cada arquivo antes de rodar.

## Arquivos que ficam só na sua máquina

O `.gitignore` deixa de fora `downloads/`, `urls.txt`, `publicacoes.csv`, `resultados_publicacao.csv`, `produtos_sem_variacao.csv`, `produtos_dimensoes.csv`, `medias_dimensoes.csv` e `.env`.

Atenção: o dicionário `CLIENTES` está dentro do código de `preparar_publicacao.py` e tem nomes de pessoas. Se o repositório for público, deixe-o privado ou mova esse cadastro para um arquivo listado no `.gitignore`.
