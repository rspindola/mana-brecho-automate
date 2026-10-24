"""
Lista os produtos que NÃO possuem variações (tamanho, cor, etc.),
exportando nome + URL para um CSV.

Um produto sem variação na Nuvemshop tem:
  - "attributes" vazio, e
  - uma única variante "virtual" com "values" vazio.

SOMENTE LEITURA: não altera nada na loja.

COMO USAR
---------
1. pip install requests
2. export NUVEMSHOP_ACCESS_TOKEN=="seu_token_novo"
3. python produtos_sem_variacao.py

Gera o arquivo produtos_sem_variacao.csv e imprime a lista no terminal.

SOBRE A URL
-----------
Usa "canonical_url" do produto quando a API retorna. Se não vier, monta
a URL como {dominio_da_loja}/produtos/{handle}/ (padrão de lojas BR),
obtendo o domínio via GET /store.
"""

import csv
import os
import sys
import time
import requests

STORE_ID = "7993893"
ACCESS_TOKEN = os.environ.get("NUVEMSHOP_ACCESS_TOKEN", "")
USER_AGENT = "Produtos Sem Variacao (seuemail@exemplo.com)"
API_VERSION = "2025-03"
BASE_URL = f"https://api.tiendanube.com/{API_VERSION}/{STORE_ID}"

OUTPUT_CSV = "produtos_sem_variacao.csv"
SLEEP_BETWEEN_CALLS = 0.3


def get_headers():
    if not ACCESS_TOKEN:
        sys.exit("Token não encontrado. Defina NUVEMSHOP_ACCESS_TOKEN= antes de rodar.")
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "User-Agent": USER_AGENT,
    }


def pick_lang(value, priority=("pt", "es", "en")):
    """Campos como name/handle vêm como dict multi-idioma."""
    if isinstance(value, dict):
        for lang in priority:
            if value.get(lang):
                return value[lang]
        return next(iter(value.values()), "")
    return value or ""


def fetch_store_url():
    """Obtém a URL base da loja (ex: https://minhaloja.lojavirtualnuvem.com.br)."""
    resp = requests.get(f"{BASE_URL}/store", headers=get_headers(), timeout=30)
    if resp.status_code != 200:
        print(f"Aviso: não consegui buscar dados da loja ({resp.status_code}). "
              "URLs sem canonical_url ficarão vazias.")
        return ""
    data = resp.json()
    url = data.get("url_with_protocol")
    if not url:
        domain = data.get("original_domain") or ""
        url = f"https://{domain}" if domain else ""
    return url.rstrip("/")


def fetch_all_products():
    products = []
    url = f"{BASE_URL}/products"
    params = {"per_page": 200, "page": 1}

    while url:
        resp = requests.get(url, headers=get_headers(), params=params, timeout=30)
        if resp.status_code != 200:
            sys.exit(f"Erro ao buscar produtos: {resp.status_code} - {resp.text}")

        batch = resp.json()
        products.extend(batch)
        print(f"  {len(products)} produtos carregados...")

        next_url = None
        link_header = resp.headers.get("Link", "")
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break

        url = next_url
        params = None
        time.sleep(SLEEP_BETWEEN_CALLS)

    return products


def has_no_variations(product):
    """True se o produto não tem atributos/variações (tamanho, cor, etc.)."""
    if product.get("attributes"):
        return False
    # Redundância: se algum variant tiver "values" preenchido, é com variação
    for variant in product.get("variants", []):
        if variant.get("values"):
            return False
    return True


def build_url(product, store_url):
    canonical = product.get("canonical_url")
    if canonical:
        return canonical
    handle = pick_lang(product.get("handle"))
    if store_url and handle:
        return f"{store_url}/produtos/{handle}/"
    return ""

def build_admin_url(product, store_url):
    """URL da página de edição do produto no painel admin."""
    if not store_url:
        return ""
    return f"{store_url}/admin/v2/products/{product['id']}"

def main():
    print("Buscando dados da loja...")
    store_url = fetch_store_url()

    print("Buscando produtos...")
    products = fetch_all_products()
    print(f"Total de produtos: {len(products)}\n")

    results = []
    for product in products:
        if has_no_variations(product):
            results.append({
                "nome": pick_lang(product.get("name")),
                "url": build_url(product, store_url),
                "url_edicao": build_admin_url(product, store_url),
                "product_id": product["id"],
                "visibilidade": product.get("visibility")
                                or ("visible" if product.get("published") else "hidden"),
            })

    print(f"Produtos SEM variação: {len(results)} de {len(products)}\n")

    for r in results:
        print(f"  {r['nome']}  ->  {r['url']}  |  editar: {r['url_edicao']}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["nome", "url", "url_edicao", "product_id", "visibilidade"]
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"\nArquivo salvo em: {os.path.abspath(OUTPUT_CSV)}")
    print("Obs: produtos com visibilidade 'hidden' retornam 404 na URL pública.")


if __name__ == "__main__":
    main()