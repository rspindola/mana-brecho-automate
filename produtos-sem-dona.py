# -*- coding: utf-8 -*-
"""
Lista todos os produtos da loja que NÃO têm o campo "Dona do Item" preenchido.

A API da Nuvemshop não tem um filtro direto para isso, então o script faz:
    1. Busca todos os produtos da loja (paginado)
    2. Busca os produtos que JÁ têm o campo preenchido (via /owners do campo)
    3. Mostra a diferença (produtos sem o campo)

Uso:
    export NUVEMSHOP_STORE_ID="7993893"
    export NUVEMSHOP_ACCESS_TOKEN="seu_token"
    python produtos_sem_dona.py
"""

import csv
import os
import sys
import time

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"
ID_CAMPO_DONA = "7370f4b493131a4f431a611a9f4d7287"  # text_list, "Dona do Item"
DOMINIO_ADMIN = "manabrechodesapegos.lojavirtualnuvem.com.br"  # domínio do painel admin da loja

DELAY_ENTRE_REQUESTS = 0.5
MAX_TENTATIVAS = 5


def request_com_retry(method: str, url: str, **kwargs) -> requests.Response:
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code != 429:
            return resp
        espera = int(resp.headers.get("Retry-After", 5 * tentativa))
        print(f"  (rate limit, aguardando {espera}s — tentativa {tentativa}/{MAX_TENTATIVAS})")
        time.sleep(espera)
    return resp


def get_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }


def buscar_todos_produtos(base_url: str, headers: dict) -> list[dict]:
    produtos = []
    pagina = 1
    while True:
        resp = request_com_retry(
            "GET",
            f"{base_url}/products",
            headers=headers,
            params={"page": pagina, "per_page": 200, "fields": "id,name,variants"},
            timeout=30,
        )
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        produtos.extend(lote)
        print(f"  página {pagina}: {len(lote)} produtos (total até agora: {len(produtos)})")
        if len(lote) < 200:
            break
        pagina += 1
        time.sleep(DELAY_ENTRE_REQUESTS)
    return produtos


def extrair_nome(produto: dict) -> str:
    nome = produto.get("name", {})
    if isinstance(nome, str):
        return nome
    if isinstance(nome, dict):
        # pega "pt" se existir; senão, o primeiro valor não-vazio disponível
        if nome.get("pt"):
            return nome["pt"]
        for v in nome.values():
            if v:
                return v
    return "(sem nome)"


def tem_estoque(produto: dict) -> bool:
    variants = produto.get("variants", [])
    if not variants:
        return False
    for v in variants:
        estoque = v.get("stock")
        # stock None = estoque não gerenciado (ilimitado) -> considera que tem estoque
        if estoque is None or estoque > 0:
            return True
    return False


def main():
    store_id = os.environ.get("NUVEMSHOP_STORE_ID")
    access_token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not access_token:
        print("ERRO: defina NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN.")
        sys.exit(1)

    base_url = API_BASE_TEMPLATE.format(store_id=store_id)
    headers = get_headers(access_token)

    print("Buscando todos os produtos da loja...")
    todos = buscar_todos_produtos(base_url, headers)
    print(f"Total: {len(todos)} produtos.\n")

    print("Buscando produtos que já têm o campo 'Dona do Item' preenchido...")
    resp = request_com_retry("GET", f"{base_url}/products/custom-fields/{ID_CAMPO_DONA}/owners", headers=headers, timeout=30)
    resp.raise_for_status()
    com_campo = {p["id"] for p in resp.json().get("products", [])}
    print(f"Total com o campo preenchido: {len(com_campo)}\n")

    sem_campo = [p for p in todos if p["id"] not in com_campo]
    sem_campo_com_estoque = [p for p in sem_campo if tem_estoque(p)]

    print(f"{len(sem_campo)} produto(s) sem o campo 'Dona do Item' preenchido.")
    print(f"{len(sem_campo_com_estoque)} deles têm estoque disponível:\n")

    linhas_csv = []
    for p in sem_campo_com_estoque:
        nome_pt = extrair_nome(p)
        url_edicao = f"https://{DOMINIO_ADMIN}/admin/products/{p['id']}"
        print(f"  id={p['id']}  {nome_pt}")
        print(f"      {url_edicao}")
        linhas_csv.append({"id": p["id"], "nome": nome_pt, "url_edicao": url_edicao})

    if linhas_csv:
        with open("produtos_sem_dona_com_estoque.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "nome", "url_edicao"])
            writer.writeheader()
            writer.writerows(linhas_csv)
        print("\nTambém salvo em 'produtos_sem_dona_com_estoque.csv'.")


if __name__ == "__main__":
    main()