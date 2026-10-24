# -*- coding: utf-8 -*-
"""
Migra os valores de "dona do item" do campo legado (texto livre, marcado
"NAO USAR") para o campo oficial (text_list, com a lista de clientes já
cadastrada), produto por produto, e depois apaga o campo legado.

Passo a passo, para cada produto que usa o campo legado:
    1. Lê o valor atual no campo legado (ex: "MC - Mirian chueke")
    2. Acha o valor equivalente já cadastrado no campo oficial, casando
       pelo código antes do traço/travessão (ex: "MC")
    3. Grava esse valor no campo oficial
    4. Limpa (null) o valor no campo legado
Ao final, deleta o campo legado.

Uso:
    export NUVEMSHOP_STORE_ID="7993893"
    export NUVEMSHOP_ACCESS_TOKEN="seu_token"
    python migrar_campo_dona.py
    # ou, se os IDs mudarem:
    python migrar_campo_dona.py --legado ID_LEGADO --oficial ID_OFICIAL
"""

import argparse
import os
import re
import sys
import time

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"

# IDs conhecidos a partir do payload que você compartilhou
ID_OFICIAL_PADRAO = "7370f4b493131a4f431a611a9f4d7287"   # text_list, "Dona do Item"
ID_LEGADO_PADRAO = "76b7c7dd83681c69c49ca8533490f72d"     # text livre, "NAO USAR"

DELAY_ENTRE_REQUESTS = 1.0  # segundos, entre cada chamada à API
MAX_TENTATIVAS = 5


def request_com_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Faz a requisição com retry automático (backoff) em caso de 429."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code != 429:
            return resp
        espera = int(resp.headers.get("Retry-After", 5 * tentativa))
        print(f"    (rate limit, aguardando {espera}s antes de tentar de novo — tentativa {tentativa}/{MAX_TENTATIVAS})")
        time.sleep(espera)
    return resp  # devolve a última resposta (ainda 429) se esgotar tentativas


def get_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }


def montar_mapa_codigo_valor(campo_oficial: dict) -> dict:
    mapa = {}
    for v in campo_oficial.get("values", []):
        texto = v["value"] if isinstance(v, dict) else v
        codigo = re.split(r"[–-]", texto, maxsplit=1)[0].strip().upper()
        mapa[codigo] = texto
    return mapa


def main():
    parser = argparse.ArgumentParser(description="Migra valores do campo legado para o campo oficial e apaga o legado.")
    parser.add_argument("--legado", default=ID_LEGADO_PADRAO, help="ID do custom field legado (a apagar)")
    parser.add_argument("--oficial", default=ID_OFICIAL_PADRAO, help="ID do custom field oficial (text_list)")
    args = parser.parse_args()

    store_id = os.environ.get("NUVEMSHOP_STORE_ID")
    access_token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not access_token:
        print("ERRO: defina NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN.")
        sys.exit(1)

    base_url = API_BASE_TEMPLATE.format(store_id=store_id)
    headers = get_headers(access_token)

    # Confirma os dois campos antes de mexer em qualquer coisa
    resp = request_com_retry("GET", f"{base_url}/products/custom-fields/{args.oficial}", headers=headers, timeout=30)
    resp.raise_for_status()
    campo_oficial = resp.json()
    print(f"Campo OFICIAL: name='{campo_oficial['name']}' value_type='{campo_oficial['value_type']}' ({len(campo_oficial.get('values', []))} valores cadastrados)")

    resp = request_com_retry("GET", f"{base_url}/products/custom-fields/{args.legado}", headers=headers, timeout=30)
    resp.raise_for_status()
    campo_legado = resp.json()
    print(f"Campo LEGADO: name='{campo_legado['name']}' value_type='{campo_legado['value_type']}'")

    if campo_oficial["value_type"] != "text_list":
        print("ERRO: o campo indicado como --oficial não é do tipo text_list. Confira os IDs.")
        sys.exit(1)

    confirm = input("\nConfirma: migrar valores do campo LEGADO acima para o campo OFICIAL, e depois apagar o LEGADO? (digite 'sim'): ")
    if confirm.strip().lower() != "sim":
        print("Cancelado.")
        return

    mapa_codigo_valor = montar_mapa_codigo_valor(campo_oficial)

    # 1. Produtos que usam o campo legado
    resp = request_com_retry("GET", f"{base_url}/products/custom-fields/{args.legado}/owners", headers=headers, timeout=30)
    resp.raise_for_status()
    produtos = resp.json().get("products", [])
    print(f"\n{len(produtos)} produto(s) usando o campo legado. Migrando...")

    migrados = 0
    for p in produtos:
        product_id = p["id"]

        # Lê o valor atual no campo legado para este produto
        resp = request_com_retry("GET", f"{base_url}/products/{product_id}/custom-fields", headers=headers, timeout=30)
        if not resp.ok:
            print(f"  produto {product_id}: ERRO ao ler valores ({resp.status_code}), pulando.")
            time.sleep(DELAY_ENTRE_REQUESTS)
            continue

        campos_do_produto = resp.json()
        entrada_legado = next((v for v in campos_do_produto if v.get("id") == args.legado), None)
        valor_legado = entrada_legado.get("value") if entrada_legado else None

        if not valor_legado:
            print(f"  produto {product_id}: sem valor no campo legado, pulando.")
            time.sleep(DELAY_ENTRE_REQUESTS)
            continue

        codigo = re.split(r"[–-]", valor_legado, maxsplit=1)[0].strip().upper()
        valor_oficial = mapa_codigo_valor.get(codigo, valor_legado)  # fallback: usa o texto original se não achar

        # Grava no campo oficial
        resp = request_com_retry(
            "PUT",
            f"{base_url}/products/{product_id}/custom-fields/values",
            headers=headers,
            json=[{"id": args.oficial, "value": valor_oficial}],
            timeout=30,
        )
        if not resp.ok:
            print(f"  produto {product_id}: ERRO ao gravar no campo oficial: {resp.status_code} {resp.text}")
            time.sleep(DELAY_ENTRE_REQUESTS)
            continue

        time.sleep(DELAY_ENTRE_REQUESTS)

        # Limpa o campo legado
        resp = request_com_retry(
            "PUT",
            f"{base_url}/products/{product_id}/custom-fields/values",
            headers=headers,
            json=[{"id": args.legado, "value": None}],
            timeout=30,
        )
        if not resp.ok:
            print(f"  produto {product_id}: aviso, não consegui limpar o campo legado: {resp.status_code} {resp.text}")

        print(f"  produto {product_id}: '{valor_legado}' -> '{valor_oficial}' migrado.")
        migrados += 1
        time.sleep(DELAY_ENTRE_REQUESTS)

    print(f"\n{migrados} produto(s) migrado(s).")

    # 2. Deleta o campo legado
    confirm2 = input(f"\nApagar definitivamente o campo legado '{campo_legado['name']}' ({args.legado})? (digite 'sim'): ")
    if confirm2.strip().lower() != "sim":
        print("Campo legado NÃO foi apagado. Rode o script de novo, ou apague manualmente depois.")
        return

    resp = request_com_retry("DELETE", f"{base_url}/products/custom-fields/{args.legado}", headers=headers, timeout=30)
    if resp.status_code in (200, 204):
        print("Campo legado removido com sucesso.")
    else:
        print(f"ERRO ao deletar campo legado: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    main()