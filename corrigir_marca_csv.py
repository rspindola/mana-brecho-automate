# -*- coding: utf-8 -*-
"""
Corrige nome de marca no publicacoes.csv (título, descrição e coluna de marca),
substituindo variações incorretas pelo nome oficial.

Uso padrão (Lorena → Lorane):
    python corrigir_marca_csv.py

Outros exemplos:
    python corrigir_marca_csv.py --de "Le lis blanc" --para "Le Lis Blanc"
    python corrigir_marca_csv.py --de "farm" --para "Farm"
    python corrigir_marca_csv.py --entrada outro.csv --saida corrigido.csv
    python corrigir_marca_csv.py --dry-run      # só mostra, não salva
"""

import argparse
import csv
import re
import shutil
from pathlib import Path

COLUNAS = ["titulo", "descricao", "marca"]


def substituir(texto: str, de: str, para: str) -> str:
    """Substitui todas as ocorrências de `de` por `para`, ignorando maiúsculas/minúsculas."""
    return re.sub(re.escape(de), para, texto, flags=re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser(description="Corrige nome de marca no publicacoes.csv.")
    parser.add_argument("--de",      default="Lorena",          help="Nome incorreto a substituir (padrão: Lorena)")
    parser.add_argument("--para",    default="Lorane",          help="Nome correto (padrão: Lorane)")
    parser.add_argument("--entrada", default="publicacoes.csv", help="CSV de entrada (padrão: publicacoes.csv)")
    parser.add_argument("--saida",   default="",                help="CSV de saída (padrão: sobrescreve a entrada)")
    parser.add_argument("--dry-run", action="store_true",       help="Mostra o que seria alterado, sem salvar")
    args = parser.parse_args()

    entrada = Path(args.entrada)
    saida   = Path(args.saida) if args.saida else entrada

    if not entrada.exists():
        print(f"ERRO: arquivo '{entrada}' não encontrado.")
        return

    with entrada.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        campos = reader.fieldnames or []
        linhas = list(reader)

    alteracoes = 0
    for linha in linhas:
        for col in COLUNAS:
            if col not in linha:
                continue
            original  = linha[col]
            corrigido = substituir(original, args.de, args.para)
            if corrigido != original:
                if args.dry_run:
                    print(f"  post: {linha.get('post_folder', '')[:40]}")
                    print(f"  [{col}] antes : {original[:100]!r}")
                    print(f"         depois: {corrigido[:100]!r}\n")
                linha[col] = corrigido
                alteracoes += 1

    if args.dry_run:
        print(f"{alteracoes} campo(s) seriam alterados. Rode sem --dry-run para salvar.")
        return

    if alteracoes == 0:
        print(f"Nenhuma ocorrência de '{args.de}' encontrada em '{entrada}'. Nada alterado.")
        return

    # Backup automático antes de sobrescrever
    if saida == entrada:
        backup = entrada.with_suffix(".bak.csv")
        shutil.copy2(entrada, backup)
        print(f"Backup salvo em '{backup}'.")

    with saida.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)

    print(f"{alteracoes} campo(s) corrigidos: '{args.de}' → '{args.para}'.")
    print(f"Arquivo salvo em '{saida}'.")


if __name__ == "__main__":
    main()
