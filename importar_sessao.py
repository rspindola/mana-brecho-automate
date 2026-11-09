# importar_sessao.py
import browser_cookie3, instaloader

L = instaloader.Instaloader()

cookies = None
for nome in ("chrome", "safari", "firefox", "brave", "edge"):
    try:
        cookies = getattr(browser_cookie3, nome)(domain_name="instagram.com")
        if any(c.name == "sessionid" for c in cookies):
            print(f"Cookies encontrados no {nome}.")
            break
        cookies = None
    except Exception as e:
        print(f"{nome}: {e}")

if not cookies:
    raise SystemExit("Nenhum navegador com sessão do Instagram encontrada.")

L.context._session.cookies.update({c.name: c.value for c in cookies})

username = L.test_login()
if not username:
    raise SystemExit("Cookies lidos, mas a sessão não é válida. Faça login de novo no navegador.")
L.context.username = username
L.save_session_to_file()
print(f"Sessão salva para {username}.")