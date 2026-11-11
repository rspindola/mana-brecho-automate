# -*- coding: utf-8 -*-
"""
Corrige o nome de uma marca em TODOS OS PRODUTOS JÁ CADASTRADOS na Nuvemshop,
substituindo ocorrências nos campos: título, descrição e marca (brand).

A busca é case-insensitive (encontra "Lorena", "lorena", "LORENA" etc.).

Requisitos:
    pip install requests
    export NUVEMSHOP_STORE_ID="seu_id"
    export NUVEMSHOP_ACCESS_TOKEN="seu_token"

Uso padrão (Lorena → Lorane):
    python corrigir_marca_loja.py

Outros exemplos:
    python corrigir_marca_loja.py --de "Le lis blanc" --para "Le Lis Blanc"
    python corrigir_marca_loja.py --dry-run        # só mostra, não altera nada
    python corrigir_marca_loja.py --apenas-marca   # atualiza só o campo brand, ignora título/descrição
"""

import argparse
import os
import re
import sys
import time

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"
DELAY_ENTRE_REQUESTS = 0.5
MAX_TENTATIVAS = 5


# ── helpers ────────────────────────────────────────────────────────────────────

def request_com_retry(method: str, url: str, **kwargs) -> requests.Response:
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code != 429:
            return resp
        espera = int(resp.headers.get("Retry-After", 5 * tentativa))
        print(f"    (rate limit — aguardando {espera}s, tentativa {tentativa}/{MAX_TENTATIVAS})")
        time.sleep(espera)
    return resp


def get_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }


def extrair_texto(campo) -> str:
    """Nuvemshop retorna name/description como dict multilíngue ou string."""
    if isinstance(campo, str):
        return campo
    if isinstance(campo, dict):
        return campo.get("pt") or next((v for v in campo.values() if v), "") or ""
    return ""


def substituir(texto: str, de: str, para: str) -> str:
    return re.sub(re.escape(de), para, texto, flags=re.IGNORECASE)


def tem_ocorrencia(texto: str, de: str) -> bool:
    return bool(re.search(re.escape(de), texto, flags=re.IGNORECASE))


# ── busca ──────────────────────────────────────────────────────────────────────

def buscar_todos_produtos(base_url: str, headers: dict) -> list[dict]:
    produtos = []
    pagina = 1
    while True:
        resp = request_com_retry(
            "GET",
            f"{base_url}/products",
            headers=headers,
            params={"page": pagina, "per_page": 200, "fields": "id,name,description,brand"},
            timeout=30,
        )
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        produtos.extend(lote)
        print(f"  página {pagina}: {len(lote)} produtos (total: {len(produtos)})")
        if len(lote) < 200:
            break
        pagina += 1
        time.sleep(DELAY_ENTRE_REQUESTS)
    return produtos


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Corrige nome de marca em título, descrição e brand de todos os produtos da loja."
    )
    parser.add_argument("--de",           default="Lorena", help="Texto incorreto a substituir (padrão: Lorena)")
    parser.add_argument("--para",         default="Lorane", help="Texto correto (padrão: Lorane)")
    parser.add_argument("--dry-run",      action="store_true", help="Apenas mostra o que seria alterado, sem salvar")
    parser.add_argument("--apenas-marca", action="store_true", help="Atualiza só o campo brand (ignora título e descrição)")
    args = parser.parse_args()

    store_id     = os.environ.get("NUVEMSHOP_STORE_ID")
    access_token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not access_token:
        print("ERRO: defina NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN.")
        sys.exit(1)

    base_url = API_BASE_TEMPLATE.format(store_id=store_id)
    headers  = get_headers(access_token)

    print(f"Buscando todos os produtos da loja (procurando '{args.de}')...\n")
    todos = buscar_todos_produtos(base_url, headers)
    print(f"\nTotal na loja: {len(todos)} produtos.\n")

    # ── detecta quais precisam ser atualizados ─────────────────────────────────
    para_atualizar = []  # lista de (produto, payload_patch)

    for p in todos:
        titulo_orig = extrair_texto(p.get("name", ""))
        desc_orig   = extrair_texto(p.get("description", ""))
        brand_orig  = (p.get("brand") or "")

        payload = {}

        if not args.apenas_marca:
            titulo_novo = substituir(titulo_orig, args.de, args.para)
            if titulo_novo != titulo_orig:
                payload["name"] = {"pt": titulo_novo}

            desc_nova = substituir(desc_orig, args.de, args.para)
            if desc_nova != desc_orig:
                payload["description"] = {"pt": desc_nova}

        brand_novo = substituir(brand_orig, args.de, args.para)
        if brand_novo != brand_orig:
            payload["brand"] = brand_novo

        if payload:
            para_atualizar.append((p, payload, titulo_orig))

    # ── relatório ──────────────────────────────────────────────────────────────
    if not para_atualizar:
        print(f"Nenhum produto com '{args.de}' encontrado. Nada a fazer.")
        return

    print(f"{len(para_atualizar)} produto(s) com '{args.de}':\n")
    for p, payload, titulo in para_atualizar:
        campos_afetados = ", ".join(
            {"name": "título", "description": "descrição", "brand": "marca"}.get(k, k)
            for k in payload
        )
        print(f"  id={p['id']:>8}  [{campos_afetados}]  {titulo[:70]}")

    if args.dry_run:
        print(f"\n--dry-run ativo: nenhuma alteração foi feita.")
        return

    # ── confirmação ────────────────────────────────────────────────────────────
    confirm = input(f"\nConfirma: corrigir '{args.de}' → '{args.para}' nesses {len(para_atualizar)} produto(s)? (digite 'sim'): ")
    if confirm.strip().lower() != "sim":
        print("Cancelado.")
        return

    # ── atualiza ───────────────────────────────────────────────────────────────
    ok = 0
    for p, payload, titulo in para_atualizar:
        pid = p["id"]
        payload["id"] = pid
        resp = request_com_retry(
            "PUT",
            f"{base_url}/products/{pid}",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.ok:
            campos = list(payload.keys())
            campos.remove("id")
            print(f"  ✅ {pid}  {titulo[:60]}  → {campos}")
            ok += 1
        else:
            print(f"  ❌ {pid}  ERRO {resp.status_code}: {resp.text[:120]}")
        time.sleep(DELAY_ENTRE_REQUESTS)

    print(f"\n{ok} de {len(para_atualizar)} produto(s) corrigido(s) com sucesso.")


if __name__ == "__main__":
    main()
