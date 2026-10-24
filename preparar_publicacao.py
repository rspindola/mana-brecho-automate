# -*- coding: utf-8 -*-
"""
Etapa 1: Prepara os posts baixados do Instagram para publicação na Nuvemshop.

Lê cada pasta em `downloads/` (gerada pelos scripts baixar_instagram.py /
baixar_por_url.py), extrai da legenda.txt:
    - título do produto
    - tamanho
    - valor
    - código da dona do item (entre parênteses após o valor)
Gera uma descrição curta e chamativa (até 300 caracteres), e lista as
imagens na ordem em que foram baixadas (ordem original do post).

Tudo isso vira uma planilha `publicacoes.csv`, que você deve REVISAR antes
de publicar. Corrija título/tamanho/valor/descrição onde precisar e marque
a coluna "status" como "ok" nas linhas que devem ser publicadas.

Uso:
    python preparar_publicacao.py
    python preparar_publicacao.py --origem downloads --saida publicacoes.csv

Opcional: se a variável de ambiente ANTHROPIC_API_KEY estiver definida,
o script usa a API da Anthropic (Claude) para gerar uma descrição mais
elaborada. Caso contrário, usa um gerador de descrição baseado em modelo
(template), que também funciona bem.
"""

import argparse
import csv
import os
import re
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


# Cadastro de clientes (código -> nome completo)
CLIENTES = {
    "DM": "Deise Moraes",
    "EM": "Eliane Marton",
    "FG": "Fernanda Guedes",
    "GG": "Gina (amiga da mamãe)",
    "IC": "Ingrid Couto",
    "LG": "Luisa Guedes",
    "MA": "Mônica Antonini",
    "MANA": "Danny e Bebby",
    "MAPR": "Maria Angélica",
    "MM": "Marcia Monteiro",
    "ND": "Nathália David",
    "NS": "Natalina Souza",
    "NSENF": "Nathalia Suman (enfermeira)",
    "SD": "Shirley Dias",
    "VB": "Vanessa Boechat",
    "RMN": "Rosa Mundo Novo",
    "RC": "Raquel Chueke",
    "MC": "Mirian Chueke",
    "ACS": "Ana Carolina Sumam",
    "LCH": "Luiza Chueke",
    "IH": "Isabella Hojn",
    "MAF": "Mariane Altomare Fisio",
    "RM": "Roberta Monteiro",
    "DT": "Débora Tomaz",
    "KT": "Karen Twardowsky",
    "RB": "Renata Bahia",
    "MEA": "Mariana Altomare",
    "ECR": "Elaine Cristina Rodrigues",
    "ER": "Eliane Rodrigues",
    "LT": "Luciane Tassis",
    "NT": "Nathalia Teich",
    "DC": "Debora Cherman",
    "NBT": "Nathalia B Teich",
    "CTM": "Cristina Thomaz de Aquino",
    "BK": "Bruna Kede Vilarejo",
    "ALCV": "Ana Lucia Coelho Fernandes",
    "MP": "Mariana Pio",
    "MV": "Milena Vieira",
    "SCF": "Simone Coelho Fernandes",
    "FRM": "Fernanda Raphael Malta",
    "LR": "Lenise RIcha"
}

STOPWORDS_TITULO = {"de", "da", "do", "das", "dos", "e", "em", "com", "para", "por", "a", "o"}


def titlecase_pt(texto: str) -> str:
    palavras = texto.strip().split()
    resultado = []
    for i, p in enumerate(palavras):
        # Preserva siglas/acrônimos curtos em maiúsculas (ex: NV, EUA, PB)
        if p.isupper() and len(p) <= 4 and p.isalpha():
            resultado.append(p)
            continue
        p_lower = p.lower()
        if i > 0 and p_lower in STOPWORDS_TITULO:
            resultado.append(p_lower)
        else:
            resultado.append(p_lower[:1].upper() + p_lower[1:])
    return " ".join(resultado)


def normalizar_valor(texto: str) -> float | None:
    s = texto.strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        partes = s.split(".")
        if len(partes[-1]) == 3:  # "2.000" -> separador de milhar
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _remover_spans(texto: str, spans: list[tuple[int, int]]) -> str:
    chars = list(texto)
    for start, end in spans:
        for i in range(start, min(end, len(chars))):
            chars[i] = " "
    return "".join(chars)


def parse_legenda(texto: str) -> dict:
    # Achata a legenda inteira (várias linhas) em uma única string, já que
    # tamanho/valor/código podem aparecer em qualquer linha, misturados.
    flat = re.sub(r"[\r\n|]+", " ", texto.strip())
    flat = re.sub(r"\s+", " ", flat)

    # --- 0. Detecta post com MAIS DE UM item na mesma legenda. Nesse caso,
    #     não tenta adivinhar nada (arriscaria misturar dados dos dois
    #     itens) — deixa tudo em branco e sinaliza para revisão manual.
    if len(re.findall(r"\bvalor\b", flat, re.IGNORECASE)) >= 2:
        return {
            "titulo": "",
            "tamanho": "",
            "valor": None,
            "codigo_dona": "",
            "legenda_raw": texto.strip(),
            "aviso": "MÚLTIPLOS ITENS neste post — preencher manualmente (parser não tenta separar automaticamente)",
        }

    spans_remover: list[tuple[int, int]] = []
    NUM = r"([\d][\d.,]*)"  # número com pontuação livre (ex: 1000, 2.000, 70,00)

    # --- 1. Código da dona: qualquer parêntese cujo conteúdo bate com um
    #     código conhecido em CLIENTES. Se houver mais de um, fica o último
    #     (geralmente o mais próximo do valor, o mais confiável).
    codigo = ""
    for m in re.finditer(r"\(([^)]+)\)", flat):
        chave = m.group(1).strip().upper()
        if chave in CLIENTES:
            codigo = chave
            spans_remover.append(m.span())

    # --- 2. Valor: se achamos um código, primeiro tenta achar um preço
    #     "colado" logo antes do parêntese do código (padrão mais comum:
    #     "... 100 (EM)", "... 2.000 (EM)", "... 490 reais (Mana)").
    valor = None
    if codigo:
        paren_start = max(s for s, e in spans_remover)
        paren_span = next(s for s in spans_remover if s[0] == paren_start)
        prefixo = flat[: paren_span[0]]
        m = re.search(NUM + r"\s*(?:reais?|reias)?\s*$", prefixo)
        if m:
            valor = normalizar_valor(m.group(1))
            spans_remover.append(m.span())

    if valor is None:
        for padrao in [
            r"valor\s*:?\s*r?\$?\s*" + NUM + r"\s*(?:reais?|reias)?",
            r"r\$\s*" + NUM + r"\s*(?:reais?|reias)?",
            NUM + r"\s*(?:reais?|reias)\b",
        ]:
            m = re.search(padrao, flat, re.IGNORECASE)
            if m:
                valor = normalizar_valor(m.group(1))
                spans_remover.append(m.span())
                break

    if valor is None:
        # último recurso: número logo antes de "(" ou do fim da string,
        # precedido de traço (ex: "Prada, tamanho 38 - 2.000")
        m = re.search(r"-\s*" + NUM + r"\s*(?=\(|$)", flat)
        if m:
            valor = normalizar_valor(m.group(1))
            spans_remover.append(m.span())

    # --- 3. Tamanho: tenta padrões com palavra-chave primeiro, depois
    #     tokens avulsos (letra de tamanho ou número de calçado/roupa).
    tamanho = ""
    for padrao in [
        r"\btamanho\s+(\S+?)\b(?:\s*\(([^)]+)\))?",
        r"\btam\.?\s+(\S+?)\b",
        r"\(\s*veste\s+([^)]+)\)",
    ]:
        m = re.search(padrao, flat, re.IGNORECASE)
        if m:
            grupos = [g for g in m.groups() if g]
            if grupos:
                tamanho = grupos[-1].strip().upper().rstrip(".,;:")
                spans_remover.append(m.span())
                break

    if not tamanho:
        m = re.search(r"\b(PP|GG|P|M|G)\b", flat)
        if m:
            tamanho = m.group(1)
            spans_remover.append(m.span())

    if not tamanho:
        m = re.search(r"\b(3[0-9]|4[0-6])\b", flat)
        if m:
            tamanho = m.group(1)
            spans_remover.append(m.span())

    # --- 4. Título: remove os trechos já identificados e limpa sobras
    titulo_txt = _remover_spans(flat, spans_remover)
    titulo_txt = re.sub(r"\bvalor\b", "", titulo_txt, flags=re.IGNORECASE)
    titulo_txt = re.sub(r"[\-–|:,]+", " ", titulo_txt)
    titulo_txt = re.sub(r"\s+", " ", titulo_txt).strip(" -–|,:")
    titulo = titlecase_pt(titulo_txt) if titulo_txt else "Item sem título"

    return {
        "titulo": titulo,
        "tamanho": tamanho,
        "valor": valor,
        "codigo_dona": codigo,
        "legenda_raw": texto.strip(),
        "aviso": "",
    }


def gerar_descricao_template(titulo: str, tamanho: str) -> str:
    tam_txt = f" Tamanho {tamanho}." if tamanho else ""
    desc = (
        f"✨ {titulo} — peça de brechó em ótimo estado, pronta para dar um "
        f"novo brilho ao seu guarda-roupa!{tam_txt} Peça única, garanta a sua "
        f"antes que acabe 💖"
    )
    return desc[:300]


def gerar_descricao_ia(titulo: str, tamanho: str, legenda_raw: str, api_key: str) -> str | None:
    if requests is None:
        return None
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-5",
                "max_tokens": 200,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Escreva uma descrição de produto para um brechó online, "
                            "em português do Brasil, chamativa e vendedora, com no "
                            "máximo 300 caracteres (conte os caracteres). "
                            f"Item: {titulo}. Tamanho: {tamanho or 'não informado'}. "
                            f"Legenda original do Instagram: {legenda_raw}. "
                            "Responda APENAS com o texto da descrição, sem aspas, "
                            "sem explicações."
                        ),
                    }
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        texto = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        texto = texto.strip()
        return texto[:300] if texto else None
    except Exception as e:
        print(f"    (aviso: geração de descrição via IA falhou, usando template. Detalhe: {e})")
        return None


def listar_imagens_ordenadas(post_folder: Path) -> list[str]:
    imagens = sorted(
        [f.name for f in post_folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
        key=lambda n: (len(n), n),  # foto_1, foto_2, ..., foto_10 na ordem certa
    )
    return imagens


def main():
    parser = argparse.ArgumentParser(description="Prepara posts do Instagram para publicação na Nuvemshop.")
    parser.add_argument("--origem", default="downloads", help="Pasta com os posts baixados (padrão: downloads)")
    parser.add_argument("--saida", default="publicacoes.csv", help="Arquivo CSV de saída (padrão: publicacoes.csv)")
    args = parser.parse_args()

    origem = Path(args.origem)
    if not origem.exists():
        print(f"ERRO: pasta '{origem}' não encontrada.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        print("ANTHROPIC_API_KEY encontrada: descrições serão geradas com IA.")
    else:
        print("ANTHROPIC_API_KEY não definida: descrições serão geradas por template (sem IA).")

    linhas_saida = []
    for post_folder in sorted(origem.iterdir()):
        if not post_folder.is_dir():
            continue
        legenda_file = post_folder / "legenda.txt"
        if not legenda_file.exists():
            print(f"  pulando {post_folder.name}: sem legenda.txt")
            continue

        legenda = legenda_file.read_text(encoding="utf-8")
        item = parse_legenda(legenda)
        imagens = listar_imagens_ordenadas(post_folder)

        codigo = item["codigo_dona"]
        nome_dona = CLIENTES.get(codigo, "")
        if codigo and not nome_dona:
            print(f"  aviso: código de dona '{codigo}' em {post_folder.name} não está no cadastro CLIENTES.")
        if item["aviso"]:
            print(f"  ATENÇÃO em {post_folder.name}: {item['aviso']}")

        descricao = None
        if api_key:
            descricao = gerar_descricao_ia(item["titulo"], item["tamanho"], item["legenda_raw"], api_key)
        if not descricao:
            descricao = gerar_descricao_template(item["titulo"], item["tamanho"])

        linhas_saida.append(
            {
                "post_folder": post_folder.name,
                "status": "revisar",  # troque para "ok" nas linhas aprovadas para publicar
                "titulo": item["titulo"],
                "descricao": descricao,
                "tamanho": item["tamanho"],
                "valor": item["valor"] if item["valor"] is not None else "",
                "codigo_dona": codigo,
                "nome_dona": nome_dona,
                "imagens": ";".join(imagens),
                "aviso": item["aviso"],
                "legenda_original": item["legenda_raw"].replace("\n", " | "),
            }
        )

    if not linhas_saida:
        print("Nenhum post encontrado para processar.")
        return

    saida = Path(args.saida)
    with saida.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas_saida[0].keys()))
        writer.writeheader()
        writer.writerows(linhas_saida)

    print(f"\n{len(linhas_saida)} posts processados. Planilha gerada em '{saida}'.")
    print("Abra o CSV, revise título/tamanho/valor/descrição, e marque status='ok' nas linhas a publicar.")


if __name__ == "__main__":
    main()
