# -*- coding: utf-8 -*-
"""
Exporta TODOS os produtos da Nuvemshop com categoria, tamanho, peso e dimensões,
e resume as medidas por tipo de roupa (categoria). SOMENTE LEITURA: não altera a loja.

Na Nuvemshop, peso e dimensões ficam na VARIAÇÃO (não no produto):
    weight (kg), width (largura, cm), height (altura, cm), depth (profundidade/comprimento, cm)
Por isso o arquivo de saída tem uma linha por variação (no seu caso, uma por tamanho).
Valores vazios ou zero contam como "não preenchido" e ficam de fora das médias.

Gera dois arquivos:
    produtos_dimensoes.csv  -> uma linha por variação: produto, categoria, tamanho, peso e medidas
    medias_dimensoes.csv    -> por categoria: quantas variações têm medidas, média e mediana de cada campo

Requisitos:
    pip install requests
    (e o arquivo categorias_nuvemshop.py na mesma pasta)

Credenciais (variáveis de ambiente; escopo read_products):
    export NUVEMSHOP_STORE_ID="seu_user_id_da_loja"
    export NUVEMSHOP_ACCESS_TOKEN="seu_access_token"

Uso:
    python exportar_dimensoes.py
    python exportar_dimensoes.py --por-tamanho          # médias por categoria E tamanho
    python exportar_dimensoes.py --saida meus_produtos.csv --saida-medias minhas_medias.csv
"""

import argparse
import csv
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

from categorias_nuvemshop import API_BASE_TEMPLATE, listar_categorias

PER_PAGE = 200
CAMPOS_MEDIDA = ["peso_kg", "largura_cm", "altura_cm", "profundidade_cm"]
SEM_CATEGORIA = "(sem categoria)"


def get_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }


def _get(url: str, headers: dict, params: dict | None = None, tentativas: int = 5):
    """GET com espera e nova tentativa quando a API pede calma (HTTP 429)."""
    resp = None
    for t in range(1, tentativas + 1):
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code != 429:
            return resp
        espera = 2 * t
        print(f"  (limite de requisições da API; aguardando {espera}s)", flush=True)
        time.sleep(espera)
    return resp


def listar_produtos(base_url: str, headers: dict) -> list[dict]:
    produtos: list[dict] = []
    pagina = 1
    while True:
        resp = _get(f"{base_url}/products", headers, {"page": pagina, "per_page": PER_PAGE})
        if resp.status_code == 404:  # página além da última
            break
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        produtos.extend(lote)
        print(f"  página {pagina}: {len(lote)} produtos (total {len(produtos)})", flush=True)
        if len(lote) < PER_PAGE:
            break
        pagina += 1
        time.sleep(0.6)  # respeita o limite de requisições da API
    return produtos


def _pt(campo) -> str:
    if isinstance(campo, dict):
        return (campo.get("pt") or next(iter(campo.values()), "") or "").strip()
    return (campo or "").strip() if isinstance(campo, str) else ""


def _num(valor):
    """Converte '2.75' em 2.75. Vazio, inválido ou zero viram None (= não preenchido)."""
    if valor in (None, ""):
        return None
    try:
        n = float(str(valor).replace(",", "."))
    except ValueError:
        return None
    return n if n > 0 else None


def categorias_do_produto(prod: dict, mapa: dict) -> list[str]:
    caminhos = []
    for c in prod.get("categories") or []:
        cid = c.get("id") if isinstance(c, dict) else c
        if cid in mapa:
            caminhos.append(mapa[cid]["caminho"])
        elif isinstance(c, dict) and _pt(c.get("name")):
            caminhos.append(_pt(c.get("name")))
    return caminhos


def montar_linhas(produtos: list[dict], mapa: dict) -> list[dict]:
    linhas = []
    for prod in produtos:
        caminhos = categorias_do_produto(prod, mapa)
        # categoria principal = a mais específica (mais níveis); em empate, a primeira
        principal = max(caminhos, key=lambda c: c.count(">")) if caminhos else SEM_CATEGORIA
        variantes = prod.get("variants") or [{}]
        for v in variantes:
            largura, altura, prof = _num(v.get("width")), _num(v.get("height")), _num(v.get("depth"))
            tamanho = " / ".join(x for x in (_pt(val) for val in v.get("values") or []) if x)
            linhas.append(
                {
                    "product_id": prod.get("id"),
                    "variant_id": v.get("id", ""),
                    "nome": _pt(prod.get("name")),
                    "categoria": principal,
                    "todas_categorias": " | ".join(caminhos),
                    "tamanho": tamanho,
                    "sku": v.get("sku") or "",
                    "peso_kg": _num(v.get("weight")),
                    "largura_cm": largura,
                    "altura_cm": altura,
                    "profundidade_cm": prof,
                    "tem_dimensoes": "sim" if (largura and altura and prof) else "não",
                    "publicado": "sim" if prod.get("published") else "não",
                }
            )
    return linhas


def resumir(linhas: list[dict], por_tamanho: bool) -> list[dict]:
    grupos: dict[tuple, list[dict]] = defaultdict(list)
    for l in linhas:
        chave = (l["categoria"], l["tamanho"]) if por_tamanho else (l["categoria"],)
        grupos[chave].append(l)

    resumo = []
    for chave, itens in sorted(grupos.items()):
        linha = {"categoria": chave[0]}
        if por_tamanho:
            linha["tamanho"] = chave[1]
        linha["variacoes"] = len(itens)
        linha["com_dimensoes"] = sum(1 for i in itens if i["tem_dimensoes"] == "sim")
        for campo in CAMPOS_MEDIDA:
            valores = [i[campo] for i in itens if i[campo] is not None]
            linha[f"{campo}_media"] = round(statistics.mean(valores), 2) if valores else ""
            linha[f"{campo}_mediana"] = round(statistics.median(valores), 2) if valores else ""
        resumo.append(linha)
    return resumo


def gravar_csv(caminho: Path, linhas: list[dict]):
    if not linhas:
        return
    with caminho.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        for l in linhas:
            w.writerow({k: ("" if v is None else v) for k, v in l.items()})


def main():
    parser = argparse.ArgumentParser(description="Exporta produtos com categoria, tamanho e dimensões (somente leitura).")
    parser.add_argument("--saida", default="produtos_dimensoes.csv", help="CSV com uma linha por variação")
    parser.add_argument("--saida-medias", default="medias_dimensoes.csv", help="CSV com as médias por categoria")
    parser.add_argument("--por-tamanho", action="store_true", help="Calcula as médias por categoria E tamanho")
    args = parser.parse_args()

    store_id = os.environ.get("NUVEMSHOP_STORE_ID")
    token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not token:
        print("ERRO: defina NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN antes de rodar.")
        sys.exit(1)

    base_url = API_BASE_TEMPLATE.format(store_id=store_id)
    headers = get_headers(token)

    print("Lendo as categorias da loja...")
    mapa = {c["id"]: c for c in listar_categorias(base_url, headers)}
    print(f"  {len(mapa)} categorias.\nLendo os produtos...")
    produtos = listar_produtos(base_url, headers)
    if not produtos:
        print("Nenhum produto encontrado.")
        return

    linhas = montar_linhas(produtos, mapa)
    resumo = resumir(linhas, args.por_tamanho)
    gravar_csv(Path(args.saida), linhas)
    gravar_csv(Path(args.saida_medias), resumo)

    com = sum(1 for l in linhas if l["tem_dimensoes"] == "sim")
    print(f"\n{len(produtos)} produtos, {len(linhas)} variações. Com largura, altura e profundidade preenchidas: {com} ({com / len(linhas):.0%}).")
    print(f"Gerei '{args.saida}' e '{args.saida_medias}'.")
    sem = [r["categoria"] for r in resumo if r["com_dimensoes"] == 0]
    if sem:
        print("Categorias SEM nenhuma variação com medidas (não há média possível): " + ", ".join(dict.fromkeys(sem)))


if __name__ == "__main__":
    main()