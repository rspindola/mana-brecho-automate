# -*- coding: utf-8 -*-
"""
Troca a marca (campo "brand") de todos os produtos que estão com um valor
antigo (ex: "Maria Brechó") para o novo nome da loja (ex: "DiDue Brechó").

A API não tem filtro direto por "brand" na listagem, então o script busca
todos os produtos, filtra localmente, e atualiza um por um.

Uso:
    export NUVEMSHOP_STORE_ID="7993893"
    export NUVEMSHOP_ACCESS_TOKEN="seu_token"
    python trocar_marca.py --de "Maria Brechó" --para "DiDue Brechó"
"""

import argparse
import os
import sys
import time

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"
DELAY_ENTRE_REQUESTS = 0.5
MAX_TENTATIVAS = 5


def request_com_retry(method: str, url: str, **kwargs) -> requests.Response:
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code != 429:
            return resp
        espera = int(resp.headers.get("Retry-After", 5 * tentativa))
        print(f"    (rate limit, aguardando {espera}s — tentativa {tentativa}/{MAX_TENTATIVAS})")
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
            params={"page": pagina, "per_page": 200, "fields": "id,name,brand"},
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
        if nome.get("pt"):
            return nome["pt"]
        for v in nome.values():
            if v:
                return v
    return "(sem nome)"


def main():
    parser = argparse.ArgumentParser(description="Troca a marca de todos os produtos que usam um valor antigo.")
    parser.add_argument("--de", required=True, help="Marca atual a ser substituída (ex: 'Maria Brechó')")
    parser.add_argument("--para", required=True, help="Nova marca (ex: 'DiDue Brechó')")
    args = parser.parse_args()

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

    alvo = [p for p in todos if (p.get("brand") or "").strip().lower() == args.de.strip().lower()]

    print(f"{len(alvo)} produto(s) com marca '{args.de}':\n")
    for p in alvo:
        print(f"  id={p['id']}  {extrair_nome(p)}")

    if not alvo:
        print("Nada para trocar.")
        return

    confirm = input(f"\nConfirma: trocar a marca desses {len(alvo)} produtos de '{args.de}' para '{args.para}'? (digite 'sim'): ")
    if confirm.strip().lower() != "sim":
        print("Cancelado.")
        return

    trocados = 0
    for p in alvo:
        product_id = p["id"]
        resp = request_com_retry(
            "PUT",
            f"{base_url}/products/{product_id}",
            headers=headers,
            json={"id": product_id, "brand": args.para},
            timeout=30,
        )
        if resp.ok:
            print(f"  produto {product_id}: marca atualizada para '{args.para}'.")
            trocados += 1
        else:
            print(f"  produto {product_id}: ERRO {resp.status_code} {resp.text}")
        time.sleep(DELAY_ENTRE_REQUESTS)

    print(f"\n{trocados} de {len(alvo)} produto(s) atualizado(s) com sucesso.")


if __name__ == "__main__":
    main()