# -*- coding: utf-8 -*-
"""
Etapa 1: Prepara os posts baixados do Instagram para publicação na Nuvemshop.

Lê cada pasta em `downloads/` (gerada pelos scripts baixar_instagram.py /
baixar_por_url.py), extrai da legenda.txt:
  - título do produto
  - tamanho
  - valor
  - código da dona do item (entre parênteses após o valor)

Gera uma descrição do produto (com IA, olhando as fotos, ou por template se
não houver chave de API), e lista as imagens na ordem em que foram baixadas
(ordem original do post).

Tudo isso vira uma planilha `publicacoes.csv`, que você deve REVISAR antes
de publicar. Corrija título/tamanho/valor/descrição onde precisar e marque
a coluna "status" como "ok" nas linhas que devem ser publicadas.

Uso:
    python preparar_publicacao.py
    python preparar_publicacao.py --origem downloads --saida publicacoes.csv

Geração da descrição (o script usa a primeira opção disponível):
  1. GEMINI_API_KEY definida  -> usa o Gemini (Google), que tem nível gratuito
     e enxerga as fotos da peça.
  2. ANTHROPIC_API_KEY definida -> usa o Claude (pago), também com as fotos.
  3. Nenhuma das duas -> usa um gerador baseado em modelo (template).
"""

import argparse
import base64
import csv
import os
import re
import time
import unicodedata
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


# ============================================================
# CONFIGURAÇÃO DA IA DE DESCRIÇÃO  (edite aqui)
# ============================================================

MODELO_IA = "claude-sonnet-5-5"  # usado só se você tiver ANTHROPIC_API_KEY

# Modelo principal do Gemini. O "lite" responde rápido e dá conta de descrições de produto.
# Para ver os nomes disponíveis na sua chave: python preparar_publicacao.py --listar-modelos
MODELO_GEMINI = "gemini-3.1-flash-lite"

# Se o principal der erro 503 (sobrecarga), demorar demais ou sumir, o script tenta estes, nesta ordem:
MODELOS_ALTERNATIVOS_GEMINI = ["gemini-3.5-flash", "gemini-flash-latest"]

TIMEOUT_GEMINI = 45        # segundos esperando cada resposta
TENTATIVAS_POR_MODELO = 2  # quantas vezes tenta o mesmo modelo antes de passar para o próximo

_ESTADO = {"modelo_gemini": MODELO_GEMINI}

# Pausa (segundos) entre posts, para não estourar o limite por minuto do plano gratuito.
PAUSA_GEMINI = 6

# Quantas fotos de cada post enviar para a IA olhar (3 costuma bastar).
MAX_FOTOS_IA = 3

# True  = a IA recebe título + legenda + fotos (descrição mais fiel à peça, gasta mais cota).
# False = a IA recebe só título + legenda (mais rápido e barato, descrição mais genérica).
USAR_FOTOS = False  # padrão: só título + legenda (rápido). Use --com-fotos para enviar as fotos também.

# Cole aqui 3 ou 4 descrições que você achou ótimas (por exemplo, geradas
# pela IA da Nuvemshop). Isso é o que mais aproxima o resultado do seu estilo.
# Exemplo de formato:
#   EXEMPLOS_DESCRICOES = [
#       "Vestido midi de malha canelada na cor verde-musgo, com decote ...",
#       "Blusa de seda estampada em tons de azul, manga bufante ...",
#   ]
EXEMPLOS_DESCRICOES: list[str] = [
    """Conheça a Bolsa de mão com alças e zíper, perfeita para quem busca praticidade e estilo em um só acessório. Confeccionada com material resistente, ela oferece durabilidade e segurança para seus pertences.
Com design compacto e elegante, é ideal para o dia a dia ou ocasiões especiais. Suas alças facilitam o transporte, enquanto o zíper garante fechamento seguro. Combine facilmente com diversos looks e leve seu essencial com muito charme!
Invista nessa bolsa versátil e transforme seu visual com funcionalidade e sofisticação.""",
    """Descubra o Vestido Toten, a escolha perfeita para quem busca estilo e conforto em uma única peça. Com um design moderno e sofisticado, este vestido valoriza sua silhueta e traz um toque de elegância para qualquer ocasião.
Confeccionado com materiais de alta qualidade, o Vestido Toten garante durabilidade e conforto para o dia a dia ou eventos especiais. Sua modelagem exclusiva oferece liberdade de movimento, ideal para acompanhar sua rotina com charme e praticidade.
Seja para um look casual ou para uma produção mais elaborada, o Vestido Toten é versátil e fácil de combinar. Aposte em acessórios minimalistas para destacar a peça ou invista em complementos coloridos para um visual mais vibrante.
Renove seu guarda-roupa com o Vestido Toten e experimente a mistura perfeita entre conforto, elegância e modernidade. Garanta já o seu e sinta-se incrível em qualquer momento!""",
    """Conheça a Papete Arezzo com Tarracha, o calçado perfeito para quem busca estilo, conforto e durabilidade em um só produto. Desenvolvida pela Arezzo, essa papete é ideal para quem valoriza praticidade sem abrir mão da elegância.
Confeccionada com materiais de alta qualidade, a papete oferece um encaixe seguro graças à tarracha ajustável, que permite o ajuste perfeito aos seus pés, garantindo conforto durante todo o dia. Seu design moderno e versátil combina facilmente com looks casuais ou até mesmo para eventos informais.
Além disso, a sola resistente proporciona excelente aderência, ideal para diversas superfícies e para o clima brasileiro. A Papete Arezzo com Tarracha é a escolha certa para quem deseja unir conforto, estilo e qualidade em um único calçado.
Invista na Papete Arezzo com Tarracha e sinta a combinação perfeita entre moda e funcionalidade!""",
]

SYSTEM_PROMPT_BASE = """Você é a redatora de moda feminina e divulgação de produtos do Maná Brechó, uma loja online de roupas, calçados e acessórios femininos de segunda mão. Sua função é escrever a descrição de cada produto para a loja virtual, sob medida para a peça.

COMO RECEBER OS DADOS
Você receberá o título da peça, o tamanho (quando houver), a legenda original do Instagram e, quando disponíveis, fotos da peça. O TÍTULO é o nome oficial da peça: use-o na abertura da descrição e nunca o contradiga. As fotos servem para acrescentar detalhes que o título não traz.

TOM DE VOZ
Sofisticado e refinado, com vocabulário elegante porém natural. Frases bem construídas, sem excesso de adjetivos, sem gírias e com no máximo uma exclamação. Fale diretamente com a cliente, com moderação.

ESTRUTURA (3 parágrafos curtos)
1. Abertura: apresente a peça pelo nome do título (por exemplo, "Conheça o Vestido...") com um gancho que destaque o que a torna especial, como cor, estampa ou silhueta.
2. Detalhes: descreva o que se vê nas fotos, como cor, estampa, modelagem, decote, manga, comprimento, caimento, acabamento, ferragens, alças, solado e fechamento. Mencione o tamanho se for informado.
3. Uso e fechamento: sugira uma ou duas ocasiões e como combinar a peça. Encerre com um convite elegante, lembrando de forma sutil que é uma peça única de brechó.

EXTENSÃO E FORMATO
De 500 a 800 caracteres, em texto corrido, sem títulos, sem listas e sem aspas. No máximo 2 emojis (o ideal é nenhum).

REGRAS DE OURO
- Descreva somente o que você vê nas fotos ou o que foi informado. Nunca invente composição do tecido ou do material (como "algodão" ou "couro legítimo"), medidas, estado de conservação ("novo", "ótimo estado"), durabilidade, resistência ou forro. A marca só pode ser citada se estiver no título, na legenda ou visível na foto.
- Se um detalhe não estiver no título, na legenda nem nas fotos, não o mencione.
- Nunca cite preço nem nomes de pessoas. Não escreva códigos ou iniciais entre parênteses: o sistema acrescenta as iniciais da dona ao final da descrição.
- Evite frases-feitas: "perfeita para quem busca", "materiais de alta qualidade", "versátil", "must-have", "imperdível", "garanta já", "invista".

ENTREGA
Responda apenas com a descrição, sem comentários antes ou depois."""


def montar_system_prompt() -> str:
    prompt = SYSTEM_PROMPT_BASE
    if EXEMPLOS_DESCRICOES:
        exemplos = "\n\n".join(f"- {e}" for e in EXEMPLOS_DESCRICOES)
        prompt += "\n\nEXEMPLOS: use-os apenas como referência de ESTRUTURA e de extensão, nunca de conteúdo. As afirmações genéricas sobre material, durabilidade e qualidade que aparecem neles NÃO podem ser repetidas, porque não são verificáveis.\n" + exemplos
    return prompt


MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


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
    "LR": "Lenise RIcha",
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
    #        não tenta adivinhar nada (arriscaria misturar dados dos dois
    #        itens) — deixa tudo em branco e sinaliza para revisão manual.
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
    #        código conhecido em CLIENTES. Se houver mais de um, fica o último
    #        (geralmente o mais próximo do valor, o mais confiável).
    codigo = ""
    for m in re.finditer(r"\(([^)]+)\)", flat):
        chave = m.group(1).strip().upper()
        if chave in CLIENTES:
            codigo = chave
            spans_remover.append(m.span())

    # --- 2. Valor: se achamos um código, primeiro tenta achar um preço
    #        "colado" logo antes do parêntese do código (padrão mais comum:
    #        "... 100 (EM)", "... 2.000 (EM)", "... 490 reais (Mana)").
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
    #        tokens avulsos (letra de tamanho ou número de calçado/roupa).
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


def gerar_descricao_ia(
    titulo: str,
    tamanho: str,
    legenda_raw: str,
    api_key: str,
    post_folder: Path,
    imagens: list[str],
) -> str | None:
    """Gera a descrição com Claude, enviando as primeiras fotos do post."""
    if requests is None:
        return None
    try:
        content = []

        # Fotos da peça (as primeiras MAX_FOTOS_IA do post)
        for nome in (imagens[:MAX_FOTOS_IA] if USAR_FOTOS else []):
            caminho = post_folder / nome
            media_type = MEDIA_TYPES.get(caminho.suffix.lower())
            if not media_type:
                continue
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(caminho.read_bytes()).decode(),
                    },
                }
            )

        content.append(
            {
                "type": "text",
                "text": (
                    f"Título (nome oficial da peça): {titulo}\n"
                    f"Tamanho: {tamanho or 'não informado'}\n"
                    f"Legenda original do Instagram: {legenda_raw}\n\n"
                    "Escreva a descrição do produto."
                ),
            }
        )

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODELO_IA,
                "max_tokens": 600,
                "system": montar_system_prompt(),
                "messages": [{"role": "user", "content": content}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        texto = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        texto = texto.strip()
        return texto or None
    except Exception as e:
        print(f"  (aviso: geração de descrição via IA falhou, usando template. Detalhe: {e})")
        return None


def _url_gemini(modelo: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


def listar_modelos_gemini(api_key: str) -> list[str]:
    """Lista os modelos da sua chave que aceitam geração de texto (generateContent)."""
    resp = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
        params={"pageSize": 200},
        timeout=30,
    )
    resp.raise_for_status()
    nomes = []
    for m in resp.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            nomes.append(m["name"].replace("models/", ""))
    return nomes


def descobrir_modelos_gemini(api_key: str, ignorar=()) -> list[str]:
    """Modelos Flash de TEXTO disponíveis, em ordem de preferência:
    1) o apelido gemini-flash-latest; 2) versões estáveis (não preview, não lite), da mais nova à mais antiga;
    3) previews; 4) versões lite. Exclui modelos de imagem, áudio, voz, 'omni', pesquisa etc."""
    try:
        nomes = listar_modelos_gemini(api_key)
    except Exception as e:
        print(f"  (aviso: não consegui listar os modelos do Gemini. Detalhe: {e})")
        return []
    excluir = (
        "image", "tts", "audio", "live", "embedding", "robotics", "computer-use", "imagen", "veo",
        "omni", "customtools", "transcribe", "nano", "banana", "antigravity", "deep-research",
        "lyria", "gemma",
    )
    candidatos = [
        n for n in nomes
        if "flash" in n and n not in ignorar and not any(x in n for x in excluir)
    ]

    def versao(n: str) -> float:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0

    candidatos.sort(key=lambda n: (n != "gemini-flash-latest", "preview" in n or "exp" in n, "lite" in n, -versao(n), n))
    return candidatos


def obter_modelo_gemini(api_key: str) -> str:
    if not _ESTADO["modelo_gemini"]:
        lista = descobrir_modelos_gemini(api_key)
        if not lista:
            raise RuntimeError("nenhum modelo Flash disponível para esta chave (rode com --listar-modelos)")
        print(f"  Modelo Gemini escolhido automaticamente: {lista[0]}")
        _ESTADO["modelo_gemini"] = lista[0]
    return _ESTADO["modelo_gemini"]


def gerar_descricao_gemini(
    titulo: str,
    tamanho: str,
    legenda_raw: str,
    api_key: str,
    post_folder: Path,
    imagens: list[str],
) -> str | None:
    """Gera a descrição com o Gemini (nível gratuito), enviando as primeiras fotos do post."""
    if requests is None:
        return None
    try:
        parts = []
        for nome in (imagens[:MAX_FOTOS_IA] if USAR_FOTOS else []):
            caminho = post_folder / nome
            media_type = MEDIA_TYPES.get(caminho.suffix.lower())
            if not media_type:
                continue
            parts.append(
                {
                    "inline_data": {
                        "mime_type": media_type,
                        "data": base64.b64encode(caminho.read_bytes()).decode(),
                    }
                }
            )
        parts.append(
            {
                "text": (
                    f"Título (nome oficial da peça): {titulo}\n"
                    f"Tamanho: {tamanho or 'não informado'}\n"
                    f"Legenda original do Instagram: {legenda_raw}\n\n"
                    "Escreva a descrição do produto."
                )
            }
        )

        corpo = {
            "systemInstruction": {"parts": [{"text": montar_system_prompt()}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.7},
        }
        headers = {"x-goog-api-key": api_key, "content-type": "application/json"}

        # Ordem de tentativa: o modelo que funcionou por último, depois os alternativos.
        fila: list[str] = []
        for nome in [_ESTADO["modelo_gemini"]] + MODELOS_ALTERNATIVOS_GEMINI:
            if nome and nome not in fila:
                fila.append(nome)
        if not fila:
            fila = [obter_modelo_gemini(api_key)]

        ultimo_erro = "sem resposta"
        for modelo in fila:
            for tentativa in range(1, TENTATIVAS_POR_MODELO + 1):
                try:
                    resp = requests.post(_url_gemini(modelo), headers=headers, json=corpo, timeout=TIMEOUT_GEMINI)
                except Exception as e:  # timeout, queda de rede etc.
                    ultimo_erro = f"{modelo}: {type(e).__name__}"
                    print(f"  ({modelo}: sem resposta em {TIMEOUT_GEMINI}s ou erro de rede; tentativa {tentativa}/{TENTATIVAS_POR_MODELO})", flush=True)
                    time.sleep(3 * tentativa)
                    continue

                if resp.status_code == 200:
                    candidatos = resp.json().get("candidates", [])
                    partes = candidatos[0].get("content", {}).get("parts", []) if candidatos else []
                    texto = "".join(p.get("text", "") for p in partes).strip()
                    if texto:
                        if modelo != _ESTADO["modelo_gemini"]:
                            print(f"  (passando a usar o modelo '{modelo}')", flush=True)
                            _ESTADO["modelo_gemini"] = modelo
                        return texto
                    ultimo_erro = f"{modelo}: resposta vazia"
                    break  # resposta vazia: passa para o próximo modelo
                if resp.status_code in (401, 403):
                    raise RuntimeError(f"chave recusada pelo Google (HTTP {resp.status_code}). Confira GEMINI_API_KEY.")
                ultimo_erro = f"{modelo}: HTTP {resp.status_code}"
                if resp.status_code == 404:
                    print(f"  ('{modelo}' indisponível para esta chave; tentando o próximo)", flush=True)
                    break
                if resp.status_code == 429:
                    print(f"  ({modelo}: limite do plano gratuito; aguardando 20s)", flush=True)
                    time.sleep(20)
                    continue
                # 500/503/504 e outros: instabilidade do Google; espera um pouco e tenta de novo
                print(f"  ({modelo}: HTTP {resp.status_code}, serviço instável; tentativa {tentativa}/{TENTATIVAS_POR_MODELO})", flush=True)
                time.sleep(4 * tentativa)

        raise RuntimeError(f"todos os modelos falharam (último erro: {ultimo_erro})")
    except Exception as e:
        print(f"  (aviso: geração de descrição via Gemini falhou, usando template. Detalhe: {e})")
        return None


def anexar_iniciais(descricao: str, codigo: str) -> str:
    """Acrescenta, no fim da descrição, as iniciais da dona entre parênteses. Ex.: ... (EM)"""
    if not codigo:
        return descricao
    marca = f"({codigo})"
    if marca in descricao:
        return descricao
    return f"{descricao.rstrip()} {marca}"


def listar_imagens_ordenadas(post_folder: Path) -> list[str]:
    imagens = sorted(
        [f.name for f in post_folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
        key=lambda n: (len(n), n),  # foto_1, foto_2, ..., foto_10 na ordem certa
    )
    return imagens


# ============================================================
# CAMPOS DE BUSCA / SEO / CATEGORIA  (edite as listas conforme a sua loja)
# ============================================================

NOME_LOJA = "Maná Brechó"

# Marcas que o script reconhece no título ou na legenda. Só preenche a marca se
# ela aparecer escrita; nunca adivinha. Acrescente as marcas que você mais vende.
MARCAS_CONHECIDAS = [
    "Arezzo", "Schutz", "Farm", "Animale", "Zara", "Osklen", "Colcci", "Prada", "Gucci",
    "Louis Vuitton", "Chanel", "Dior", "Michael Kors", "Calvin Klein", "Tommy Hilfiger",
    "Lacoste", "Nike", "Adidas", "Havaianas", "Melissa", "Dumond", "Carmen Steffens",
    "Capodarte", "Santa Lolla", "Le Lis Blanc", "Maria Filó", "Lança Perfume", "Hering",
    "Cantão", "Iódice", "Granado", "Shoulder", "Triton", "Richards", "Ellus",
]

# (palavras-chave do TÍTULO, nome EXATO da categoria na sua Nuvemshop).
# A primeira regra que combinar vence, então a ordem importa.
# Ajuste os nomes à direita para ficarem idênticos aos das suas categorias.
CATEGORIAS_POR_PALAVRA = [
    (["macacao", "macaquinho", "jardineira"], "Macacões"),
    (["vestido"], "Vestidos"),
    (["conjunto"], "Conjuntos"),
    (["biquini", "maio", "saida de praia", "sunga"], "Moda Praia"),
    (["casaco", "jaqueta", "blazer", "cardigan", "sobretudo", "trench", "colete", "kimono"], "Casacos"),
    (["blusa", "camisa", "camiseta", "regata", "cropped", "body", "top", "polo", "bata", "tshirt", "t shirt", "suéter", "sueter", "tricot"], "Blusas"),
    (["calca", "legging", "jeans", "bermuda", "short", "shorts"], "Calças e Shorts"),
    (["saia"], "Saias"),
    (["bolsa", "mochila", "clutch", "carteira", "pochete", "necessaire"], "Bolsas"),
    (["sandalia", "papete", "sapato", "tenis", "bota", "rasteira", "sapatilha", "scarpin", "salto", "chinelo", "mule", "anabela", "tamanco", "oxford", "mocassim"], "Calçados"),
    (["cinto", "lenco", "oculos", "brinco", "colar", "pulseira", "anel", "chapeu", "bone", "echarpe", "cachecol", "relogio"], "Acessórios"),
]


def _normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", txt.lower()).strip()


def _cortar_palavra(txt: str, limite: int) -> str:
    if len(txt) <= limite:
        return txt
    return txt[:limite].rsplit(" ", 1)[0].rstrip(" ,;:-–|")


def gerar_slug(titulo: str, limite: int = 60) -> str:
    slug = _normalizar(titulo).replace(" ", "-")
    if len(slug) > limite:
        slug = slug[:limite].rsplit("-", 1)[0]  # corta na última palavra inteira
    return slug.strip("-")


def detectar_marca(titulo: str, legenda: str) -> str:
    alvo = f" {_normalizar(titulo + ' ' + legenda)} "
    for marca in MARCAS_CONHECIDAS:
        if f" {_normalizar(marca)} " in alvo:
            return marca
    return ""


def detectar_categoria(titulo: str) -> str:
    alvo = f" {_normalizar(titulo)} "
    for palavras, categoria in CATEGORIAS_POR_PALAVRA:
        if any(f" {_normalizar(p)} " in alvo for p in palavras):
            return categoria
    return ""


def gerar_titulo_seo(titulo: str, limite: int = 70) -> str:
    for modelo in (f"{titulo} - Brechó Feminino | {NOME_LOJA}", f"{titulo} | {NOME_LOJA}"):
        if len(modelo) <= limite:
            return modelo
    return _cortar_palavra(titulo, limite)


def gerar_descricao_seo(descricao: str, limite: int = 160) -> str:
    """Primeiras frases da descrição que cabem em 160 caracteres (sem as iniciais da dona)."""
    texto = re.sub(r"\s*\([A-Za-z]{1,6}\)\s*$", "", descricao.strip())
    texto = re.sub(r"\s+", " ", texto)
    saida = ""
    for frase in re.split(r"(?<=[.!?])\s+", texto):
        candidata = (saida + " " + frase).strip()
        if len(candidata) > limite:
            break
        saida = candidata
    if not saida:
        saida = _cortar_palavra(texto, limite - 1) + "…"
    return saida


def gerar_tags(titulo: str, tamanho: str, marca: str, categoria: str, max_tags: int = 10) -> str:
    tags: list[str] = []
    if not titulo.lower().startswith("item sem"):
        for w in titulo.split():
            wl = w.lower().strip(".,;:()")
            if len(wl) > 2 and wl not in STOPWORDS_TITULO:
                tags.append(wl)
    tags += ["brechó", "moda feminina"]
    if marca:
        tags.append(marca.lower())
    if categoria:
        tags.append(categoria.lower())
    if tamanho:
        tags.append(f"tamanho {tamanho.lower()}")
    unicas = list(dict.fromkeys(tags))
    return ", ".join(unicas[:max_tags])


def gerar_campos_busca(titulo: str, tamanho: str, legenda: str, descricao: str) -> dict:
    marca = detectar_marca(titulo, legenda)
    categoria = detectar_categoria(titulo)
    return {
        "categoria": categoria,
        "marca": marca,
        "tags": gerar_tags(titulo, tamanho, marca, categoria),
        "titulo_seo": gerar_titulo_seo(titulo),
        "descricao_seo": gerar_descricao_seo(descricao),
        "url_produto": gerar_slug(titulo),
    }


def main():
    parser = argparse.ArgumentParser(description="Prepara posts do Instagram para publicação na Nuvemshop.")
    parser.add_argument("--origem", default="downloads", help="Pasta com os posts baixados (padrão: downloads)")
    parser.add_argument("--saida", default="publicacoes.csv", help="Arquivo CSV de saída (padrão: publicacoes.csv)")
    parser.add_argument("--com-fotos", action="store_true", help="Envia também as fotos para a IA (mais fiel à peça, porém bem mais lento)")
    parser.add_argument("--limite", type=int, default=0, help="Processa só os N primeiros posts (útil para testar)")
    parser.add_argument("--listar-modelos", action="store_true", help="Lista os modelos Gemini disponíveis para a sua chave e sai")
    args = parser.parse_args()

    global USAR_FOTOS
    if args.com_fotos:
        USAR_FOTOS = True
    modo_fotos = "com fotos" if USAR_FOTOS else "sem fotos: só título e legenda"

    if args.listar_modelos:
        chave = os.environ.get("GEMINI_API_KEY")
        if not chave or requests is None:
            print("Defina GEMINI_API_KEY (e instale 'requests') para listar os modelos.")
            return
        try:
            for nome in listar_modelos_gemini(chave):
                print(nome)
        except Exception as e:
            print(f"Erro ao listar modelos: {e}")
        return

    origem = Path(args.origem)
    if not origem.exists():
        print(f"ERRO: pasta '{origem}' não encontrada.")
        return

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if gemini_key:
        print(f"GEMINI_API_KEY encontrada: descrições serão geradas com o Gemini ({modo_fotos}).")
    elif anthropic_key:
        print(f"ANTHROPIC_API_KEY encontrada: descrições serão geradas com o Claude ({modo_fotos}).")
    else:
        print("Nenhuma chave de API definida (GEMINI_API_KEY ou ANTHROPIC_API_KEY): descrições por template (sem IA).")

    pastas = [d for d in sorted(origem.iterdir()) if d.is_dir()]
    if args.limite:
        pastas = pastas[: args.limite]
    total = len(pastas)
    print(f"{total} posts para processar. (Ctrl+C interrompe e salva o que já foi feito.)\n")

    linhas_saida = []

    try:
        for i, post_folder in enumerate(pastas, 1):
            t0 = time.time()
            print(f"[{i}/{total}] {post_folder.name} ...", flush=True)
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
            arquivo_desc = post_folder / "descricao.txt"
            texto_desc = arquivo_desc.read_text(encoding="utf-8").replace("\r\n", "\n").strip() if arquivo_desc.exists() else ""
            if texto_desc:
                # descrição já escrita (ex.: pelo agente do Cursor): tem prioridade sobre a IA e o template
                descricao = texto_desc
                print("      usando descricao.txt desta pasta", flush=True)
            elif gemini_key:
                descricao = gerar_descricao_gemini(
                    item["titulo"],
                    item["tamanho"],
                    item["legenda_raw"],
                    gemini_key,
                    post_folder,
                    imagens,
                )
                time.sleep(PAUSA_GEMINI)
            elif anthropic_key:
                descricao = gerar_descricao_ia(
                    item["titulo"],
                    item["tamanho"],
                    item["legenda_raw"],
                    anthropic_key,
                    post_folder,
                    imagens,
                )
            if not descricao:
                descricao = gerar_descricao_template(item["titulo"], item["tamanho"])
                if (gemini_key or anthropic_key) and not item["aviso"]:
                    item["aviso"] = "Descrição por TEMPLATE (a IA falhou) — gerar de novo ou escrever à mão"

            # Regra da loja: a descrição termina com as iniciais da dona entre parênteses.
            descricao = anexar_iniciais(descricao, codigo)
            print(f"      pronto em {time.time() - t0:.0f}s", flush=True)
            if not codigo and not item["aviso"]:
                item["aviso"] = "Iniciais da dona NÃO identificadas no título — conferir (ou incluir o código em CLIENTES)"

            extras = gerar_campos_busca(item["titulo"], item["tamanho"], item["legenda_raw"], descricao)
            if not extras["categoria"]:
                item["aviso"] = (item["aviso"] + " | " if item["aviso"] else "") + "Categoria não identificada — preencher"

            linhas_saida.append(
                {
                    "post_folder": post_folder.name,
                    "status": "revisar",  # troque para "ok" nas linhas aprovadas para publicar
                    "titulo": item["titulo"],
                    "descricao": descricao,
                    "categoria": extras["categoria"],
                    "marca": extras["marca"],
                    "tags": extras["tags"],
                    "titulo_seo": extras["titulo_seo"],
                    "descricao_seo": extras["descricao_seo"],
                    "url_produto": extras["url_produto"],
                    "tamanho": item["tamanho"],
                    "valor": item["valor"] if item["valor"] is not None else "",
                    "codigo_dona": codigo,
                    "nome_dona": nome_dona,
                    "imagens": ";".join(imagens),
                    "aviso": item["aviso"],
                    "legenda_original": item["legenda_raw"].replace("\n", " | "),
                }
            )

    except KeyboardInterrupt:
        print("\nInterrompido (Ctrl+C). Salvando os posts já processados...")

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