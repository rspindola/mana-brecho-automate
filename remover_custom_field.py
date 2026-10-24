# -*- coding: utf-8 -*-
"""
Utilitário: remove um custom field da Nuvemshop que está "preso" porque
produtos ainda o utilizam.

Faz isso em 2 passos:
    1. Busca todos os produtos que usam o campo (GET /custom-fields/{id}/owners)
       e desassocia cada um (value = null).
    2. Deleta o campo (DELETE /custom-fields/{id}).

Uso:
    export NUVEMSHOP_STORE_ID="7993893"
    export NUVEMSHOP_ACCESS_TOKEN="seu_token"
    python remover_custom_field.py --id 76b7c7dd83681c69c49ca8533490f72d
"""

import argparse
import os
import sys

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"


def get_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }


def main():
    parser = argparse.ArgumentParser(description="Remove um custom field preso por produtos que o usam.")
    parser.add_argument("--id", required=True, help="ID (UUID) do custom field a remover")
    args = parser.parse_args()

    store_id = os.environ.get("NUVEMSHOP_STORE_ID")
    access_token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not access_token:
        print("ERRO: defina NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN.")
        sys.exit(1)

    base_url = API_BASE_TEMPLATE.format(store_id=store_id)
    headers = get_headers(access_token)

    # Confirma qual campo é, antes de mexer
    resp = requests.get(f"{base_url}/products/custom-fields/{args.id}", headers=headers, timeout=30)
    resp.raise_for_status()
    campo = resp.json()
    print(f"Campo encontrado: name='{campo['name']}' key='{campo['key']}' value_type='{campo['value_type']}'")

    confirm = input("Confirma que é ESSE campo que você quer apagar? (digite 'sim' para continuar): ")
    if confirm.strip().lower() != "sim":
        print("Cancelado.")
        return

    # 1. Busca produtos que usam o campo
    resp = requests.get(f"{base_url}/products/custom-fields/{args.id}/owners", headers=headers, timeout=30)
    resp.raise_for_status()
    dados = resp.json()
    produtos = dados.get("products", [])
    print(f"{len(produtos)} produto(s) usando este campo. Desassociando...")

    for p in produtos:
        product_id = p["id"]
        resp = requests.put(
            f"{base_url}/products/{product_id}/custom-fields/values",
            headers=headers,
            json=[{"id": args.id, "value": None}],
            timeout=30,
        )
        if resp.ok:
            print(f"  produto {product_id}: desassociado.")
        else:
            print(f"  produto {product_id}: ERRO {resp.status_code} {resp.text}")

    # 2. Deleta o campo
    resp = requests.delete(f"{base_url}/products/custom-fields/{args.id}", headers=headers, timeout=30)
    if resp.status_code in (200, 204):
        print(f"\nCampo '{campo['name']}' ({args.id}) removido com sucesso.")
    else:
        print(f"\nERRO ao deletar campo: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    main()
