# -*- coding: utf-8 -*-
"""
Gera dimensoes_padrao.csv (tabela EDITÁVEL de medidas padrão por categoria)
a partir do medias_dimensoes.csv produzido por exportar_dimensoes.py.

Usa a MEDIANA de cada categoria. Ignora "(sem categoria)" e categorias com poucas
variações medidas (o mínimo padrão é 2), porque a mediana de 1 peça não é um padrão.

Uso:
    python gerar_dimensoes_padrao.py
    python gerar_dimensoes_padrao.py --medias medias_dimensoes.csv --saida dimensoes_padrao.csv --min-amostra 3
"""

import argparse
import csv
from pathlib import Path

CAMPOS = ["peso_kg", "largura_cm", "altura_cm", "profundidade_cm"]


# ============================================================
# Funções usadas pelo preparar_publicacao.py
# ============================================================

def carregar_tabela(caminho: str = "dimensoes_padrao.csv") -> dict:
    """Carrega o CSV de dimensões padrão em um dicionário {categoria: {campo: valor}}."""
    tabela = {}
    p = Path(caminho)
    if not p.exists():
        return tabela
    with p.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cat = (row.get("categoria") or "").strip()
            if not cat:
                continue
            tabela[cat] = {c: row.get(c, "") for c in CAMPOS}
    return tabela


def buscar_dimensoes(categoria: str, tabela: dict) -> tuple[dict, str]:
    """Retorna (dimensoes, categoria_usada).

    Tenta primeiro a categoria exata, depois a categoria-mãe (tudo antes do
    último ' > '), subindo até encontrar ou esgotar os níveis.
    """
    cat = categoria.strip()
    while cat:
        if cat in tabela:
            dims = tabela[cat]
            # Considera "encontrado" só se ao menos um campo estiver preenchido
            if any(dims.get(c) for c in CAMPOS):
                return dims, cat
        # Sobe um nível: "Roupas > Vestidos > Festa" → "Roupas > Vestidos"
        partes = cat.rsplit(" > ", 1)
        if len(partes) == 1:
            break
        cat = partes[0]
    return {}, ""


def usou_categoria_mae(categoria_original: str, categoria_usada: str) -> bool:
    """Retorna True quando as dimensões vieram de uma categoria-mãe (não da exata)."""
    return bool(categoria_usada) and categoria_usada != categoria_original.strip()


# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Gera a tabela de medidas padrão por categoria.")
    parser.add_argument("--medias", default="medias_dimensoes.csv")
    parser.add_argument("--saida", default="dimensoes_padrao.csv")
    parser.add_argument("--min-amostra", type=int, default=2, help="mínimo de variações com medidas na categoria")
    args = parser.parse_args()

    origem = Path(args.medias)
    if not origem.exists():
        print(f"ERRO: '{origem}' não encontrado. Rode antes o exportar_dimensoes.py.")
        return

    linhas, ignoradas = [], []
    with origem.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            categoria = (r.get("categoria") or "").strip()
            if not categoria or categoria == "(sem categoria)":
                continue
            n = int(float(r.get("com_dimensoes") or 0))
            if n < args.min_amostra:
                ignoradas.append(f"{categoria} (n={n})")
                continue
            linha = {"categoria": categoria}
            for campo in CAMPOS:
                linha[campo] = r.get(f"{campo}_mediana", "")
            linha["amostra"] = n
            linha["observacao"] = "amostra pequena: confira" if n < 5 else ""
            linhas.append(linha)

    with Path(args.saida).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["categoria"] + CAMPOS + ["amostra", "observacao"])
        w.writeheader()
        w.writerows(linhas)

    print(f"{len(linhas)} categorias gravadas em '{args.saida}'. Abra o arquivo e corrija o que quiser.")
    if ignoradas:
        print("Ficaram de fora (poucas medidas): " + "; ".join(ignoradas))


if __name__ == "__main__":
    main()