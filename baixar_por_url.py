"""
Baixador de posts do Instagram POR URL (fotos + legenda), organizado por pasta.

Diferente do baixar_instagram.py (que varre o perfil inteiro), este script
baixa só os posts cujas URLs você fornecer. Isso evita a consulta pesada
"web_profile_info" que costuma ser a primeira a levar 429.

Cada post vira uma pasta:
    downloads/
        2024-06-01_18-30-00_ABC123/
            foto_1.jpg
            foto_2.jpg   (se for carrossel)
            legenda.txt

Requisitos:
    pip install instaloader

Uso:
    1) Crie um arquivo urls.txt com uma URL de post por linha, exemplo:
        https://www.instagram.com/p/ABC123xyz/
        https://www.instagram.com/p/DEF456uvw/

    2) Rode:
        python baixar_por_url.py urls.txt --login seu_usuario

Observações:
- Continua exigindo login pra reduzir (não eliminar) chance de bloqueio.
- Se seu perfil/IP estiver mesmo sinalizado, mesmo assim pode dar 429.
  Nesse caso o único remédio real é esperar mais tempo (horas) antes de
  tentar de novo, e evitar múltiplas tentativas seguidas.
"""

import argparse
import random
import re
import sys
import time
from pathlib import Path

import instaloader


def extrair_shortcode(url: str) -> str | None:
    match = re.search(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def baixar_por_urls(urls_file: str, destino: str, login_user: str | None, delay_min: float, delay_max: float):
    L = instaloader.Instaloader(
        dirname_pattern=destino,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
    )

    if login_user:
        try:
            L.load_session_from_file(login_user)
            print(f"Sessão carregada para {login_user}.")
        except FileNotFoundError:
            print(f"Fazendo login como {login_user} (senha será pedida)...")
            L.interactive_login(login_user)
            L.save_session_to_file()

    base_path = Path(destino)
    base_path.mkdir(parents=True, exist_ok=True)
    ja_baixados = {p.name.split("_")[-1] for p in base_path.iterdir() if p.is_dir()}

    urls_path = Path(urls_file)
    if not urls_path.exists():
        print(f"ERRO: arquivo '{urls_file}' não encontrado no diretório atual ({Path.cwd()}).")
        sys.exit(1)

    # utf-8-sig remove BOM se existir (comum em arquivos salvos no Windows/Notepad)
    raw_text = urls_path.read_text(encoding="utf-8-sig", errors="ignore")
    urls = [l.strip() for l in raw_text.splitlines() if "instagram.com" in l]

    if not urls:
        print(f"ATENÇÃO: nenhuma URL válida encontrada em '{urls_file}'.")
        print(f"Tamanho do arquivo: {urls_path.stat().st_size} bytes.")
        print("Conteúdo bruto lido (repr, para depurar encoding):")
        print(repr(raw_text[:300]))
        sys.exit(1)

    print(f"{len(urls)} URLs encontradas em {urls_file}.")

    count = 0
    for i, url in enumerate(urls, start=1):
        shortcode = extrair_shortcode(url)
        if not shortcode:
            print(f"[{i}] URL inválida, pulando: {url}")
            continue

        if shortcode in ja_baixados:
            print(f"[{i}] Post {shortcode} já baixado, pulando.")
            continue

        try:
            post = instaloader.Post.from_shortcode(L.context, shortcode)
        except Exception as e:
            print(f"[{i}] Erro ao buscar post {shortcode}: {e}")
            continue

        date_str = post.date_local.strftime("%Y-%m-%d_%H-%M-%S")
        post_folder = base_path / f"{date_str}_{shortcode}"
        post_folder.mkdir(parents=True, exist_ok=True)

        try:
            if post.typename == "GraphSidecar":
                for j, node in enumerate(post.get_sidecar_nodes(), start=1):
                    if node.is_video:
                        continue
                    L.download_pic(
                        filename=str(post_folder / f"foto_{j}"),
                        url=node.display_url,
                        mtime=post.date_local,
                    )
            elif not post.is_video:
                L.download_pic(
                    filename=str(post_folder / "foto_1"),
                    url=post.url,
                    mtime=post.date_local,
                )
            else:
                print(f"[{i}] Post {shortcode} é vídeo/reel, pulando (imagens apenas).")
        except Exception as e:
            print(f"[{i}] Erro ao baixar mídia do post {shortcode}: {e}")

        (post_folder / "legenda.txt").write_text(post.caption or "", encoding="utf-8")

        count += 1
        print(f"[{i}] Post {shortcode} salvo em {post_folder}")

        if i < len(urls):
            pausa = random.uniform(delay_min, delay_max)
            print(f"    aguardando {pausa:.1f}s antes do próximo post...")
            time.sleep(pausa)

    print(f"\nConcluído. {count} posts novos baixados em '{destino}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baixa posts específicos do Instagram (por URL), organizados por pasta.")
    parser.add_argument("urls_file", help="Arquivo .txt com uma URL de post por linha")
    parser.add_argument("--destino", default="downloads", help="Pasta de destino (padrão: downloads)")
    parser.add_argument("--login", default=None, help="Seu usuário do Instagram, para logar")
    parser.add_argument("--delay-min", type=float, default=8.0, help="Pausa mínima em segundos entre posts (padrão: 8)")
    parser.add_argument("--delay-max", type=float, default=15.0, help="Pausa máxima em segundos entre posts (padrão: 15)")
    args = parser.parse_args()

    baixar_por_urls(args.urls_file, args.destino, args.login, args.delay_min, args.delay_max)
