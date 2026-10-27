# -*- coding: utf-8 -*-
"""
Etapa 2: Publica na Nuvemshop os itens aprovados na planilha `publicacoes.csv`
(gerada pelo preparar_publicacao.py).

Só publica linhas onde a coluna "status" está como "ok".

Para cada linha:
    - Cria o produto (nome + descrição)
    - Cria a variação de tamanho, com o valor informado e estoque = 1
      (sem tamanho na planilha, a variação é criada como "ÚNICO")
    - Envia as imagens na mesma ordem em que foram baixadas do post
    - Associa o campo personalizado "dona_do_item" com "CÓDIGO - Nome"
    - Preenche categoria, marca, tags, título SEO, descrição SEO e URL do produto
    - Preenche peso e dimensões da variação (colunas peso_kg, largura_cm, altura_cm e profundidade_cm)
      (colunas categoria, marca, tags, titulo_seo, descricao_seo e url_produto do CSV)

Sobre a categoria: o script só usa categorias que JÁ EXISTEM na loja. Ele lê a
lista da Nuvemshop, converte o nome da coluna "categoria" no ID correspondente e
NUNCA cria uma categoria nova. Se o nome não bater com nenhuma categoria da loja,
o produto é criado sem categoria e o script avisa.

Requisitos:
    pip install requests
    (e o arquivo categorias_nuvemshop.py na mesma pasta)

Credenciais (obrigatório, via variáveis de ambiente):
    export NUVEMSHOP_STORE_ID="seu_user_id_da_loja"
    export NUVEMSHOP_ACCESS_TOKEN="seu_access_token"

Como conseguir essas credenciais:
    Você precisa de um app próprio (privado) na Nuvemshop com os escopos
    read_products e write_products. Crie em https://partners.nuvemshop.com.br,
    siga o fluxo OAuth descrito na documentação da API, e guarde o
    access_token e o user_id (= store_id) retornados.
    Doc: https://tiendanube.github.io/api-documentation/authentication

Uso:
    python publicar_nuvemshop.py
    python publicar_nuvemshop.py --planilha publicacoes.csv --origem downloads
"""

import argparse
import base64
import csv
import html
import os
import re
import sys
import time
from pathlib import Path

import requests

from categorias_nuvemshop import listar_categorias, resolver_categoria

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"
CAMPO_DONA_NOME = "dona_do_item"
TAMANHO_PADRAO = "ÚNICO"  # usado quando a linha não tem tamanho


def get_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }


def garantir_campo_dona(base_url: str, headers: dict) -> tuple[str, dict]:
    """
    Localiza o custom field 'dona_do_item' já existente (por key/slug, não por
    nome de exibição) e retorna (id_do_campo, mapa_codigo->valor_exato).

    NUNCA cria um novo campo: se não encontrar, interrompe com erro, porque
    criar um duplicado bagunça o painel (como já aconteceu uma vez).
    """
    resp = requests.get(f"{base_url}/products/custom-fields", headers=headers, timeout=30)
    resp.raise_for_status()
    campos = resp.json()

    candidatos = [c for c in campos if c.get("key") == CAMPO_DONA_NOME or c.get("slug") == CAMPO_DONA_NOME]
    # Nunca considera campos marcados como legado/não usar, mesmo que o key/slug bata
    candidatos = [
        c for c in candidatos
        if "nao usar" not in (c.get("name") or "").lower()
        and c.get("namespace") != "legacy"
    ]
    # Prioriza o campo do tipo text_list (o cadastro "oficial" com a lista de clientes)
    campo = next((c for c in candidatos if c.get("value_type") == "text_list"), None)

    if not campo:
        print(f"ERRO: não encontrei um custom field text_list válido com key/slug '{CAMPO_DONA_NOME}'.")
        print("Campos encontrados (para conferência):")
        for c in campos:
            print(f"  id={c.get('id')} name={c.get('name')!r} namespace={c.get('namespace')} value_type={c.get('value_type')}")
        print("Ajuste manualmente e rode de novo. Este script NUNCA cria um campo novo automaticamente.")
        sys.exit(1)

    print(f"Usando custom field existente: id={campo['id']} name='{campo['name']}' value_type='{campo['value_type']}'")

    # Mapa código -> valor exato cadastrado, ex: "MC" -> "MC - Mirian chueke"
    mapa_codigo_valor = {}
    for v in campo.get("values", []):
        texto = v["value"] if isinstance(v, dict) else v
        # separador pode ser "–" (travessão) ou "-" (hífen)
        codigo = re.split(r"[–-]", texto, maxsplit=1)[0].strip().upper()
        mapa_codigo_valor[codigo] = texto

    return campo["id"], mapa_codigo_valor


def descricao_para_html(texto: str) -> str:
    """Parágrafos separados por linha em branco viram <p>; quebra simples vira <br>. Escapa caracteres especiais."""
    texto = (texto or "").replace("\r\n", "\n")
    blocos = [b.strip() for b in re.split(r"\n\s*\n", texto) if b.strip()]
    return "".join(f"<p>{html.escape(b, quote=False).replace(chr(10), '<br>')}</p>" for b in blocos)


def criar_produto(base_url: str, headers: dict, titulo: str, descricao: str, tamanho: str, valor: float) -> dict:
    tamanho = (tamanho or "").strip() or TAMANHO_PADRAO  # sem tamanho: cria a variação "ÚNICO"
    payload = {
        "name": {"pt": titulo},
        "description": {"pt": descricao_para_html(descricao)},
        "attributes": [{"pt": "Tamanho"}],
        "visibility": "hidden",  # cria como rascunho: não aparece na loja nem é acessível pela URL até você revisar e publicar manualmente
        "variants": [
            {
                "price": valor,
                "stock_management": True,
                "stock": 1,
                "values": [{"pt": tamanho}],
            }
        ],
    }
    resp = requests.post(f"{base_url}/products", headers=headers, json=payload, timeout=30)
    if not resp.ok:
        print(f"    ERRO ao criar produto: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json()


def _tentar_put(base_url: str, headers: dict, product_id: int, payload: dict) -> tuple[bool, str]:
    resp = requests.put(f"{base_url}/products/{product_id}", headers=headers, json=payload, timeout=30)
    if resp.ok:
        return True, ""
    return False, f"{resp.status_code} {resp.text[:300]}"


def enriquecer_produto(base_url: str, headers: dict, product_id: int, linha: dict, categoria_id) -> list[str]:
    """
    Preenche categoria, marca, tags, SEO e URL do produto já criado.

    Primeiro tenta enviar tudo de uma vez. Se a Nuvemshop recusar, tenta campo a campo,
    testando formatos alternativos (por exemplo, tags como texto ou como lista), e informa
    exatamente qual campo falhou e por quê. O produto já existe, então nada aqui o impede.
    Retorna a lista de campos que não foi possível preencher.
    """
    marca = (linha.get("marca") or "").strip()
    tags = (linha.get("tags") or "").strip()
    titulo_seo = (linha.get("titulo_seo") or "").strip()
    descricao_seo = (linha.get("descricao_seo") or "").strip()
    slug = (linha.get("url_produto") or "").strip()

    # para cada campo: formatos candidatos, do mais provável ao alternativo
    campos: dict[str, list] = {}
    if marca:
        campos["brand"] = [marca]
    if tags:
        campos["tags"] = [tags, [t.strip() for t in tags.split(",") if t.strip()]]
    if titulo_seo:
        campos["seo_title"] = [titulo_seo]
    if descricao_seo:
        campos["seo_description"] = [descricao_seo]
    if slug:
        # 2ª opção acrescenta o id do produto, caso a URL já exista em outro produto
        campos["handle"] = [{"pt": slug}, {"pt": f"{slug}-{product_id}"}, slug]
    if categoria_id:
        campos["categories"] = [[categoria_id]]

    if not campos:
        return []

    ok, erro = _tentar_put(base_url, headers, product_id, {k: v[0] for k, v in campos.items()})
    if ok:
        print(f"    campos de busca/SEO/categoria preenchidos: {', '.join(campos)}")
        return []

    print(f"    aviso: envio em bloco recusado ({erro}). Tentando campo a campo...")
    falhas = []
    for campo, opcoes in campos.items():
        time.sleep(0.6)
        erro_campo = ""
        for valor in opcoes:
            ok, erro_campo = _tentar_put(base_url, headers, product_id, {campo: valor})
            if ok:
                break
            time.sleep(0.4)
        if ok:
            print(f"      {campo}: ok")
        else:
            print(f"      ERRO no campo '{campo}': {erro_campo}")
            falhas.append(campo)
    return falhas


def _num_csv(valor):
    try:
        n = float(str(valor or "").replace(",", "."))
    except ValueError:
        return None
    return n if n > 0 else None


def preencher_dimensoes(base_url: str, headers: dict, produto: dict, linha: dict) -> list[str]:
    """
    Preenche peso (kg) e largura, altura e profundidade (cm) da variação, com os valores das colunas
    peso_kg, largura_cm, altura_cm e profundidade_cm do CSV. Tenta enviar como texto ("0.30") e, se a
    Nuvemshop recusar, como número. Colunas vazias são ignoradas. Retorna ["dimensoes"] se falhar.
    """
    medidas = {
        "weight": _num_csv(linha.get("peso_kg")),
        "width": _num_csv(linha.get("largura_cm")),
        "height": _num_csv(linha.get("altura_cm")),
        "depth": _num_csv(linha.get("profundidade_cm")),
    }
    medidas = {k: v for k, v in medidas.items() if v}
    if not medidas:
        print("    aviso: linha sem peso/dimensões; a variação ficará sem medidas.")
        return []

    variantes = produto.get("variants") or []
    if not variantes:
        print("    aviso: a resposta da Nuvemshop não trouxe a variação; não consegui preencher as medidas.")
        return ["dimensoes"]

    falhou = False
    for v in variantes:
        url = f"{base_url}/products/{produto['id']}/variants/{v['id']}"
        ok, erro = False, ""
        for formato in (lambda x: f"{x:.2f}", lambda x: x):
            resp = requests.put(url, headers=headers, json={k: formato(val) for k, val in medidas.items()}, timeout=30)
            if resp.ok:
                ok = True
                break
            erro = f"{resp.status_code} {resp.text[:300]}"
            time.sleep(0.4)
        if ok:
            resumo = ", ".join(f"{k}={val}" for k, val in medidas.items())
            print(f"    medidas da variação {v['id']} preenchidas: {resumo}")
        else:
            print(f"    ERRO ao preencher as medidas da variação {v['id']}: {erro}")
            falhou = True
        time.sleep(0.4)
    return ["dimensoes"] if falhou else []


def enviar_imagens(base_url: str, headers: dict, product_id: int, post_folder: Path, nomes_imagens: list[str]):
    for i, nome in enumerate(nomes_imagens, start=1):
        caminho = post_folder / nome
        if not caminho.exists():
            print(f"    aviso: imagem '{nome}' não encontrada em {post_folder}, pulando.")
            continue
        b64 = base64.b64encode(caminho.read_bytes()).decode("utf-8")
        resp = requests.post(
            f"{base_url}/products/{product_id}/images",
            headers=headers,
            json={"attachment": b64, "filename": nome, "position": i},
            timeout=60,
        )
        if not resp.ok:
            print(f"    ERRO ao enviar imagem {nome}: {resp.status_code} {resp.text}")
        else:
            print(f"    imagem {i}/{len(nomes_imagens)} enviada: {nome}")
        time.sleep(1)  # evita bater no rate limit da API


def associar_dona(base_url: str, headers: dict, product_id: int, campo_dona_id: str, mapa_codigo_valor: dict, codigo: str, nome: str):
    if not codigo:
        return
    valor_campo = mapa_codigo_valor.get(codigo.upper())
    if not valor_campo:
        # Código não está na lista já cadastrada: usa "CÓD - Nome" como novo valor
        valor_campo = f"{codigo} - {nome}" if nome else codigo
        print(f"    aviso: código '{codigo}' não encontrado nos valores já cadastrados, criando novo valor '{valor_campo}'.")
    resp = requests.put(
        f"{base_url}/products/{product_id}/custom-fields/values",
        headers=headers,
        json=[{"id": campo_dona_id, "value": valor_campo}],
        timeout=30,
    )
    if not resp.ok:
        print(f"    ERRO ao associar dona do item: {resp.status_code} {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="Publica itens aprovados na Nuvemshop.")
    parser.add_argument("--planilha", default="publicacoes.csv", help="CSV gerado pelo preparar_publicacao.py")
    parser.add_argument("--origem", default="downloads", help="Pasta com os posts baixados (padrão: downloads)")
    args = parser.parse_args()

    store_id = os.environ.get("NUVEMSHOP_STORE_ID")
    access_token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not access_token:
        print("ERRO: defina as variáveis de ambiente NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN antes de rodar.")
        print("Veja instruções no topo deste arquivo.")
        sys.exit(1)

    base_url = API_BASE_TEMPLATE.format(store_id=store_id)
    headers = get_headers(access_token)

    planilha = Path(args.planilha)
    if not planilha.exists():
        print(f"ERRO: planilha '{planilha}' não encontrada. Rode primeiro o preparar_publicacao.py.")
        sys.exit(1)

    origem = Path(args.origem)

    campo_dona_id, mapa_codigo_valor = garantir_campo_dona(base_url, headers)

    # Categorias que já existem na loja (somente leitura: este script nunca cria categoria)
    try:
        categorias = listar_categorias(base_url, headers)
        print(f"{len(categorias)} categorias existentes na loja carregadas.")
    except Exception as e:
        categorias = []
        print(f"aviso: não consegui ler as categorias da loja ({e}). Os produtos serão criados SEM categoria.")

    with planilha.open(encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f))

    def esta_aprovado(linha: dict) -> bool:
        valor_bruto = linha.get("status") or linha.get("ok") or ""
        return valor_bruto.strip().lower() in ("ok", "sim", "yes", "1", "true")

    aprovadas = [l for l in linhas if esta_aprovado(l)]
    print(f"{len(aprovadas)} de {len(linhas)} linhas marcadas como aprovadas para publicar.\n")

    resultados = []
    for i, linha in enumerate(aprovadas, start=1):
        titulo = linha["titulo"].strip()
        print(f"[{i}/{len(aprovadas)}] Publicando: {titulo}")

        try:
            valor = float(linha["valor"])
        except (ValueError, KeyError):
            print(f"    ERRO: valor inválido ('{linha.get('valor')}'), pulando este item.")
            resultados.append({**linha, "resultado": "erro_valor_invalido"})
            continue

        post_folder = origem / linha["post_folder"]
        nomes_imagens = [n for n in linha["imagens"].split(";") if n]

        try:
            produto = criar_produto(base_url, headers, titulo, linha["descricao"], linha["tamanho"], valor)
            product_id = produto["id"]
            print(f"    produto criado: id={product_id}")

            enviar_imagens(base_url, headers, product_id, post_folder, nomes_imagens)
            associar_dona(base_url, headers, product_id, campo_dona_id, mapa_codigo_valor, linha["codigo_dona"], linha["nome_dona"])

            # Categoria: só converte o nome em ID de uma categoria que já existe
            nome_categoria = (linha.get("categoria") or "").strip()
            categoria_id = None
            if nome_categoria:
                categoria_id = resolver_categoria(nome_categoria, categorias)
                if categoria_id is None:
                    print(f"    aviso: a categoria '{nome_categoria}' não existe na loja (ou é ambígua); produto ficará SEM categoria.")
                    if categorias:
                        exemplos = ", ".join(c["caminho"] for c in categorias[:15])
                        print(f"           categorias existentes: {exemplos}{' ...' if len(categorias) > 15 else ''}")
            else:
                print("    aviso: linha sem categoria; produto ficará sem categoria.")

            falhas = enriquecer_produto(base_url, headers, product_id, linha, categoria_id)
            falhas += preencher_dimensoes(base_url, headers, produto, linha)

            resultados.append({
                **linha,
                "resultado": "ok",
                "product_id": product_id,
                "categoria_id": categoria_id or "",
                "campos_com_erro": ";".join(falhas),
            })
        except Exception as e:
            print(f"    ERRO ao publicar '{titulo}': {e}")
            resultados.append({**linha, "resultado": f"erro: {e}"})

        time.sleep(2)  # pausa entre produtos, evita rate limit

    # salva um log do que foi feito
    log_path = planilha.with_name("resultados_publicacao.csv")
    if resultados:
        # união dos nomes de coluna, pois linhas com erro têm menos colunas que as publicadas
        campos = []
        for r in resultados:
            for k in r.keys():
                if k not in campos:
                    campos.append(k)
        with log_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=campos, restval="")
            writer.writeheader()
            writer.writerows(resultados)
        print(f"\nLog salvo em '{log_path}'.")

    ok_count = sum(1 for r in resultados if r.get("resultado") == "ok")
    print(f"\nConcluído: {ok_count} produtos publicados com sucesso, {len(resultados) - ok_count} com erro.")
    com_falha = [r for r in resultados if r.get("campos_com_erro")]
    if com_falha:
        print(f"ATENÇÃO: {len(com_falha)} produto(s) com campos de busca/SEO não preenchidos (veja a coluna 'campos_com_erro' do log).")
    if ok_count:
        print("\nATENÇÃO: os produtos foram criados como OCULTOS (rascunho) — não aparecem na loja ainda.")
        print("Revise cada um no painel da Nuvemshop e mude a visibilidade para 'Visível' quando estiver pronto para publicar.")


if __name__ == "__main__":
    main()