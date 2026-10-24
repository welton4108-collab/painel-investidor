#!/usr/bin/env python3
"""
Gera as páginas da aba Insights a partir da planilha "Estudos".

1. Busca os estudos publicados no Apps Script (?action=posts).
2. Grava dados/posts.json (lista usada pela aba Insights do site).
3. Cria insights/<endereço>/index.html para cada estudo, com título,
   resumo e imagem para a prévia no WhatsApp e no LinkedIn.
4. Remove as páginas de estudos que deixaram de ser publicados.

Só usa a biblioteca padrão do Python.
"""
import html, json, os, re, shutil, sys, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("LEADS_API") or (
    "https://script.google.com/macros/s/"
    "AKfycbyKDNfPPI7u0yieLIwe61DyFEZy3To4ye5m2exLEKYUnBRK3lGd3Mw-t10PjWGAGcgs/exec")
SITE = os.environ.get("SITE_URL", "https://painel.objetivoprimeiro.com")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def baixar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "painel-insights/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    return t


def texto_para_html(txt):
    """Formatação simples: parágrafos, ## subtítulo, - lista, **negrito**, [link](url)."""
    out, lista = [], []

    def fecha_lista():
        if lista:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in lista) + "</ul>")
            lista.clear()

    for bloco in re.split(r"\n\s*\n", txt.replace("\r", "").strip()):
        for linha in bloco.split("\n"):
            s = linha.strip()
            if not s:
                continue
            if s.startswith("## "):
                fecha_lista(); out.append(f"<h2>{inline(s[3:])}</h2>")
            elif s.startswith(("- ", "• ")):
                lista.append(s[2:])
            else:
                fecha_lista(); out.append(f"<p>{inline(s)}</p>")
        fecha_lista()
    return "\n".join(out)


def data_br(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{int(m[3])} de {MESES[int(m[2]) - 1]} de {m[1]}" if m else (iso or "")


def slug_seguro(s):
    return re.sub(r"[^a-z0-9-]", "", (s or "").lower())[:80]


def main():
    try:
        dados = baixar(API + "?action=posts")
    except Exception as e:
        print(f"Não foi possível buscar os estudos: {e}", file=sys.stderr)
        sys.exit(1)
    if not dados.get("ok"):
        print(f"Resposta inesperada: {dados}", file=sys.stderr)
        sys.exit(1)

    modelo = open(os.path.join(RAIZ, "insights", "_modelo.html"), encoding="utf-8").read()
    posts, ativos = [], set()
    for p in dados.get("posts", []):
        slug = slug_seguro(p.get("slug"))
        if not slug or slug.startswith("_"):
            continue
        ativos.add(slug)
        url = f"{SITE}/insights/{slug}/"
        imagem = p.get("imagem") or f"{SITE}/og-padrao.png"
        resumo = (p.get("resumo") or "").strip()
        capa = f'<img class="capa" src="{html.escape(p["imagem"])}" alt="">' if p.get("imagem") else ""
        pdf_box = ""
        if p.get("pdf"):
            pdf_box = """<section class="box pdfbox" aria-labelledby="pdf-t">
    <h2 id="pdf-t">Baixe o estudo completo em PDF</h2>
    <div id="pdf-body">
      <p>Informe seu nome e e-mail para liberar o download.</p>
      <form class="form" id="pdf-form" novalidate>
        <div><label for="pdf-nome">Nome</label><input id="pdf-nome" autocomplete="name"></div>
        <div><label for="pdf-email">E-mail</label><input id="pdf-email" type="email" autocomplete="email"></div>
        <div class="hp" aria-hidden="true"><label for="pdf-url">Não preencha</label><input id="pdf-url" tabindex="-1" autocomplete="off"></div>
        <label class="consent full"><input id="pdf-lgpd" type="checkbox"><span>Autorizo o envio de conteúdos por e-mail, conforme a LGPD e o <a href="/privacidade.html">aviso de privacidade</a>.</span></label>
        <div class="full"><button class="btn" type="submit">Liberar o PDF</button></div>
        <p class="err full" id="pdf-err" hidden></p>
      </form>
    </div>
  </section>"""
        cfg = json.dumps({"slug": slug, "titulo": p["titulo"], "resumo": resumo, "url": url,
                          "api": API, "pdf": p.get("pdf", "")}, ensure_ascii=False).replace("</", "<\\/")
        pagina = (modelo
                  .replace("{{TITULO}}", html.escape(p["titulo"]))
                  .replace("{{DESCRICAO}}", html.escape(resumo[:200]))
                  .replace("{{URL}}", html.escape(url))
                  .replace("{{IMAGEM}}", html.escape(imagem))
                  .replace("{{DATA_ISO}}", html.escape(p.get("data", "")))
                  .replace("{{DATA_BR}}", html.escape(data_br(p.get("data", ""))))
                  .replace("{{RESUMO}}", html.escape(resumo))
                  .replace("{{CAPA}}", capa)
                  .replace("{{CORPO}}", texto_para_html(p.get("texto", "")))
                  .replace("{{PDF_BOX}}", pdf_box)
                  .replace("{{CFG}}", cfg))
        pasta = os.path.join(RAIZ, "insights", slug)
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "index.html"), "w", encoding="utf-8") as f:
            f.write(pagina)
        posts.append({"slug": slug, "titulo": p["titulo"], "data": p.get("data", ""),
                      "resumo": resumo, "pdf": bool(p.get("pdf")), "imagem": p.get("imagem", "")})

    for nome in os.listdir(os.path.join(RAIZ, "insights")):
        caminho = os.path.join(RAIZ, "insights", nome)
        if os.path.isdir(caminho) and nome not in ativos and not nome.startswith("_"):
            shutil.rmtree(caminho)

    with open(os.path.join(RAIZ, "dados", "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"posts": posts}, f, ensure_ascii=False, indent=1)
    print(f"{len(posts)} estudo(s) publicado(s).")


if __name__ == "__main__":
    main()
