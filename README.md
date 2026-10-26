# Maná Brechó — publicação na Nuvemshop

Os scripts deste repositório pegam posts do Instagram, montam a planilha `publicacoes.csv` e criam os produtos na Nuvemshop. Os produtos nascem ocultos (rascunho): só aparecem na loja depois que você muda a visibilidade no painel.

Fluxo:

1. Baixar os posts para `downloads/`.
2. Gerar a descrição de cada peça, pelo Gemini ou pelo Cursor.
3. Revisar `publicacoes.csv` e marcar `status` como `ok`.
4. Publicar na Nuvemshop.

## Requisitos

Python 3 e as bibliotecas usadas pelos scripts:

```bash
pip install instaloader requests
```

Credenciais ficam em variáveis de ambiente. Não cole tokens no código nem no git. O arquivo `.env` já está no `.gitignore`.

| Variável | Quando |
| --- | --- |
| `GEMINI_API_KEY` | Gerar descrições com o Gemini |
| `ANTHROPIC_API_KEY` | Alternativa paga (Claude), se não houver chave do Gemini |
| `NUVEMSHOP_STORE_ID` | Publicar ou consultar a loja |
| `NUVEMSHOP_ACCESS_TOKEN` | Publicar ou consultar a loja |

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

## 2. Gerar as descrições

`preparar_publicacao.py` lê cada pasta de `downloads/`, tira da `legenda.txt` o título, o tamanho, o valor e o código da dona (entre parênteses depois do valor) e grava `publicacoes.csv`.

A descrição de cada pasta segue esta ordem:

1. Se existir `descricao.txt` na pasta, esse texto entra na planilha.
2. Se não existir e `GEMINI_API_KEY` estiver definida, o Gemini escreve a descrição.
3. Se não houver Gemini e `ANTHROPIC_API_KEY` estiver definida, o Claude escreve.
4. Sem arquivo e sem chave, o script usa um texto de template e marca um aviso na planilha.

O script acrescenta as iniciais da dona no final da descrição. O nome correspondente ao código está no dicionário `CLIENTES`, no início de `preparar_publicacao.py`. Código novo precisa ser incluído ali; caso contrário a planilha avisa que o código não está no cadastro.

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

O modelo principal está em `MODELO_GEMINI`, dentro de `preparar_publicacao.py` (`gemini-3.1-flash-lite`). Se ele falhar ou demorar, o script tenta `gemini-3.5-flash` e `gemini-flash-latest`. Há uma pausa de 6 segundos entre posts para respeitar o limite do plano gratuito. `Ctrl+C` interrompe e salva o que já foi processado.

Pastas que já têm `descricao.txt` não chamam a API, mesmo com a chave definida. Dá para misturar: o Cursor escreve um lote e o Gemini preenche o restante.

### Pelo Cursor

A regra [`.cursor/rules/descricao-produtos.mdc`](.cursor/rules/descricao-produtos.mdc) vale para arquivos em `downloads/`. Ela pede uma descrição em texto puro, UTF-8, de 500 a 800 caracteres, em três parágrafos, só com o que está na legenda ou nas fotos.

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

Abra `publicacoes.csv`. Cada linha nasce com `status` igual a `revisar`. Confira título, tamanho, valor, descrição, categoria, marca e o aviso da coluna `aviso`. Troque `status` para `ok` só nas linhas que devem ir para a loja.

Valores aceitos como aprovado: `ok`, `sim`, `yes`, `1`, `true`.

## 4. Publicar na Nuvemshop

```bash
export NUVEMSHOP_STORE_ID="seu_user_id"
export NUVEMSHOP_ACCESS_TOKEN="seu_token"
python publicar_nuvemshop.py
```

O script publica somente as linhas com status aprovado. Para cada uma, cria o produto, a variação de tamanho com estoque 1, envia as fotos na ordem do post e preenche o campo `dona_do_item` com `CÓDIGO - Nome`. O campo precisa já existir na loja como `text_list`; o script não cria um campo novo.

```bash
python publicar_nuvemshop.py --planilha publicacoes.csv --origem downloads
```

O log fica em `resultados_publicacao.csv`. Os produtos ficam ocultos. No painel da Nuvemshop, revise cada um e mude a visibilidade para visível quando estiver pronto.

## Scripts auxiliares

Todos leem a loja com `NUVEMSHOP_STORE_ID` e `NUVEMSHOP_ACCESS_TOKEN`, exceto `produtos_sem_variacao.py`, que usa só `NUVEMSHOP_ACCESS_TOKEN`.

| Script | O que faz | Comando |
| --- | --- | --- |
| `produtos_sem_variacao.py` | Lista produtos sem variação (tamanho, cor) e grava `produtos_sem_variacao.csv`. Só leitura. | `python produtos_sem_variacao.py` |
| `produtos-sem-dona.py` | Lista produtos sem o campo "Dona do Item". | `python produtos-sem-dona.py` |
| `migrar_campo_dona.py` | Copia a dona do campo legado para o campo oficial e apaga o legado. | `python migrar_campo_dona.py` |
| `trocar_marca.py` | Troca a marca de todos os produtos de um valor para outro. | `python trocar_marca.py --de "Maria Brechó" --para "DiDue Brechó"` |
| `remover_custom_field.py` | Desassocia um campo personalizado dos produtos e depois o apaga. | `python remover_custom_field.py --id ID_DO_CAMPO` |

`migrar_campo_dona.py` e `remover_custom_field.py` alteram a loja. Confira os IDs no topo de cada arquivo antes de rodar.

## Arquivos que ficam só na sua máquina

O `.gitignore` deixa de fora `downloads/`, `urls.txt`, `publicacoes.csv`, `resultados_publicacao.csv`, `produtos_sem_variacao.csv` e `.env`.
