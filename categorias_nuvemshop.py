# -*- coding: utf-8 -*-
"""
Consulta e casamento de categorias JÁ CADASTRADAS na Nuvemshop.

Este módulo só LÊ as categorias da loja (GET /categories). Ele NUNCA cria,
altera ou apaga categoria. Se nenhuma categoria combinar com o produto, o
resultado é "sem categoria", e quem decide o que fazer é você, no CSV.

Usado por preparar_publicacao.py (para sugerir a categoria real no CSV) e por
publicar_nuvemshop.py (para converter o nome da categoria no ID da loja).
"""

import os
import re
import unicodedata

import requests

API_BASE_TEMPLATE = "https://api.tiendanube.com/2025-03/{store_id}"

_STOP = {"de", "da", "do", "das", "dos", "e", "em", "com", "para", "a", "o", "as", "os"}
_GENERICAS = {"moda", "feminina", "feminino", "roupa", "roupas", "brecho", "peca", "pecas"}


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", txt.lower()).strip()


def _stem(palavra: str) -> str:
    # tolera plural simples: "vestidos" casa com "vestido"
    return palavra[:-1] if len(palavra) > 3 and palavra.endswith("s") else palavra


def _tokens(txt: str) -> list[str]:
    return [_stem(w) for w in _norm(txt).split() if w not in _STOP]


def _chave(txt: str) -> str:
    return " ".join(_tokens(txt))


def _nome_pt(campo) -> str:
    if isinstance(campo, dict):
        return (campo.get("pt") or next(iter(campo.values()), "") or "").strip()
    return (campo or "").strip()


def listar_categorias(base_url: str, headers: dict) -> list[dict]:
    """Retorna [{'id', 'nome', 'caminho', 'e_subcategoria'}], onde caminho é 'Pai > Filha'."""
    brutas: list[dict] = []
    pagina = 1
    while True:
        resp = requests.get(
            f"{base_url}/categories",
            headers=headers,
            params={"page": pagina, "per_page": 200},
            timeout=30,
        )
        if resp.status_code == 404:  # página além da última
            break
        resp.raise_for_status()
        dados = resp.json()
        if not dados:
            break
        brutas.extend(dados)
        if len(dados) < 200:
            break
        pagina += 1

    por_id = {c["id"]: c for c in brutas}

    def id_do_pai(c):
        pai = c.get("parent")
        return pai.get("id") if isinstance(pai, dict) else pai

    resultado = []
    for c in brutas:
        partes = [_nome_pt(c.get("name"))]
        visto = {c["id"]}
        atual = c
        while True:
            pid = id_do_pai(atual)
            if not pid or pid in visto or pid not in por_id:
                break
            visto.add(pid)
            atual = por_id[pid]
            partes.insert(0, _nome_pt(atual.get("name")))
        resultado.append(
            {
                "id": c["id"],
                "nome": partes[-1],
                "caminho": " > ".join(p for p in partes if p),
                "e_subcategoria": len(partes) > 1,
            }
        )
    return resultado


def carregar_categorias_da_loja() -> list[dict] | None:
    """Lê as categorias usando NUVEMSHOP_STORE_ID e NUVEMSHOP_ACCESS_TOKEN. None se não houver credenciais."""
    store_id = os.environ.get("NUVEMSHOP_STORE_ID")
    token = os.environ.get("NUVEMSHOP_ACCESS_TOKEN")
    if not store_id or not token:
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "ManaBrecho (contato@manabrecho.com.br)",
    }
    return listar_categorias(API_BASE_TEMPLATE.format(store_id=store_id), headers)


def resolver_categoria(texto: str, categorias: list[dict]):
    """Converte o nome (ou 'Pai > Filha') no ID de uma categoria existente. None se não achar ou se for ambíguo."""
    chave = _chave(texto)
    if not chave:
        return None
    por_caminho = [c for c in categorias if _chave(c["caminho"]) == chave]
    if len(por_caminho) == 1:
        return por_caminho[0]["id"]
    por_nome = [c for c in categorias if _chave(c["nome"]) == chave]
    if len(por_nome) == 1:
        return por_nome[0]["id"]
    return None


def sugerir_categoria(titulo: str, categorias: list[dict], regras: list) -> str:
    """
    Sugere uma categoria EXISTENTE para o título. Devolve o caminho ('Pai > Filha') ou ''.
    1) Categoria cujo nome inteiro aparece no título (a mais específica vence).
    2) Regras de sinônimos [(palavras-chave, nome sugerido)], só valem se o nome existir na loja.
    """
    palavras_titulo = set(_tokens(titulo))
    achadas = []
    for c in categorias:
        palavras_cat = set(_tokens(c["nome"]))
        if palavras_cat and palavras_cat <= palavras_titulo:
            achadas.append((len(palavras_cat), c["e_subcategoria"], c))
    if achadas:
        achadas.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return achadas[0][2]["caminho"]

    # Sinônimos: a regra diz "se o título tem estas palavras, a ideia é esta categoria".
    # A categoria real é escolhida entre as que EXISTEM na loja, por palavras em comum.
    alvo = f" {_norm(titulo)} "
    for palavras, sugerido in regras:
        achadas_kw = [p for p in palavras if f" {_norm(p)} " in alvo]
        if not achadas_kw:
            continue
        stems_kw = {t for p in achadas_kw for t in _tokens(p)} - {_stem(g) for g in _GENERICAS}
        stems_sug = set(_tokens(sugerido)) - {_stem(g) for g in _GENERICAS}
        candidatos = []
        for c in categorias:
            tc = set(_tokens(c["nome"])) - {_stem(g) for g in _GENERICAS}
            if not tc:
                continue
            em_kw, em_sug = len(tc & stems_kw), len(tc & stems_sug)
            if em_kw or em_sug:
                candidatos.append((em_kw, em_sug, c["e_subcategoria"], c))
        if candidatos:
            # prefere a que casa com a palavra específica do título, depois com o nome sugerido, depois a subcategoria
            candidatos.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            return candidatos[0][3]["caminho"]
    return ""