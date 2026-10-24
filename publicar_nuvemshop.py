# -*- coding: utf-8 -*-
"""
Etapa 2: Publica na Nuvemshop os itens aprovados na planilha `publicacoes.csv`
(gerada pelo preparar_publicacao.py).

Só publica linhas onde a coluna "status" está como "ok".

Para cada linha:
    - Cria o produto (nome + descrição)
    - Cria a variação de tamanho, com o valor informado e estoque = 1
    - Envia as imagens na mesma ordem em que foram baixadas do post
    - Associa o campo personalizado "dona_do_item" com "CÓDIGO - Nome"

Requisitos:
    pip install requests

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
import os
import re
import sys
import time
from pathlib import Path

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"
CAMPO_DONA_NOME = "dona_do_item"


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


def criar_produto(base_url: str, headers: dict, titulo: str, descricao: str, tamanho: str, valor: float) -> dict:
    payload = {
        "name": {"pt": titulo},
        "description": {"pt": f"<p>{descricao}</p>"},
        "attributes": [{"pt": "Tamanho"}] if tamanho else [],
        "visibility": "hidden",  # cria como rascunho: não aparece na loja nem é acessível pela URL até você revisar e publicar manualmente
        "variants": [
            {
                "price": valor,
                "stock_management": True,
                "stock": 1,
                "values": [{"pt": tamanho}] if tamanho else [],
            }
        ],
    }
    resp = requests.post(f"{base_url}/products", headers=headers, json=payload, timeout=30)
    if not resp.ok:
        print(f"    ERRO ao criar produto: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json()


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

            resultados.append({**linha, "resultado": "ok", "product_id": product_id})
        except Exception as e:
            print(f"    ERRO ao publicar '{titulo}': {e}")
            resultados.append({**linha, "resultado": f"erro: {e}"})

        time.sleep(2)  # pausa entre produtos, evita rate limit

    # salva um log do que foi feito
    log_path = planilha.with_name("resultados_publicacao.csv")
    if resultados:
        with log_path.open("w", newline="", encoding="utf-8-sig") as f:
            campos = list(resultados[0].keys())
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            writer.writerows(resultados)
        print(f"\nLog salvo em '{log_path}'.")

    ok_count = sum(1 for r in resultados if r.get("resultado") == "ok")
    print(f"\nConcluído: {ok_count} produtos publicados com sucesso, {len(resultados) - ok_count} com erro.")
    if ok_count:
        print("\nATENÇÃO: os produtos foram criados como OCULTOS (rascunho) — não aparecem na loja ainda.")
        print("Revise cada um no painel da Nuvemshop e mude a visibilidade para 'Visível' quando estiver pronto para publicar.")


if __name__ == "__main__":
    main()