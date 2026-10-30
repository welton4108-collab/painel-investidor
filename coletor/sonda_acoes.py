"""Sonda temporária: baixa os arquivos da CVM e da B3 e mostra a estrutura."""
import csv, io, sys, zipfile, urllib.request, time
UA = {"User-Agent": "Mozilla/5.0 (painel-investidor)"}
def baixar(url):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
            b = r.read()
        print(f"OK {url} {len(b)/1e6:.1f} MB {time.time()-t:.0f}s"); return b
    except Exception as e:
        print(f"FALHA {url}: {e}"); return None
def ler_csv(b, nome=None):
    txt = b.decode("latin-1")
    return list(csv.DictReader(io.StringIO(txt), delimiter=";"))

cad = baixar("https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv")
if cad:
    rows = ler_csv(cad); print("CAD cols:", list(rows[0].keys()))
    at = [r for r in rows if r.get("SIT") == "ATIVO"]; print("ativos:", len(at))
    from collections import Counter
    print("SIT:", Counter(r.get("SIT") for r in rows).most_common(6))
    print("TP_MERC:", Counter(r.get("TP_MERC") for r in at).most_common(8))
    print("SETORES:", Counter(r.get("SETOR_ATIV") for r in at).most_common(60))
    for r in rows:
        if r.get("CD_CVM") in ("9512", "19348", "5410"): print("CAD", r)

for nome, url in [("FCA", "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_2026.zip"),
                  ("ITR", "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip"),
                  ("DFP", "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2025.zip")]:
    b = baixar(url)
    if not b: continue
    z = zipfile.ZipFile(io.BytesIO(b))
    print(nome, "arquivos:", z.namelist())
    for f in z.namelist():
        rows = ler_csv(z.read(f))
        if not rows: continue
        alvo = [r for r in rows if r.get("CD_CVM") in ("9512", "19348") or "PETROBRAS" in r.get("DENOM_CIA", r.get("Nome_Empresarial", "")).upper()]
        print(f"--- {f} ({len(rows)} linhas) cols={list(rows[0].keys())}")
        if "valor_mobiliario" in f:
            for r in rows:
                if r.get("CNPJ_Companhia","").startswith("33.000.167") or r.get("Codigo_CVM") in ("9512","19348"): print("  VM", r)
        if any(k in f for k in ("_DRE_con", "_BPA_con", "_BPP_con", "_DFC_MI_con", "composicao_capital")):
            for r in alvo[:400]:
                cd = r.get("CD_CONTA", "")
                if "composicao" in f or cd.count(".") <= 2 or cd.startswith("6.01.01") or cd.startswith("6.03"):
                    print("  ", {k: r[k] for k in r if k in ("CD_CVM","DT_REFER","VERSAO","ESCALA_MOEDA","ORDEM_EXERC","DT_INI_EXERC","DT_FIM_EXERC","CD_CONTA","DS_CONTA","VL_CONTA")} if "composicao" not in f else r)

b = baixar("https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2026.ZIP")
if b:
    z = zipfile.ZipFile(io.BytesIO(b)); print("COTAHIST:", z.namelist())
    linhas = z.read(z.namelist()[0]).decode("latin-1").splitlines()
    print("linhas:", len(linhas)); print(linhas[0]); 
    for l in linhas:
        if l[12:24].strip() in ("PETR4", "TAEE11") and l[2:10] >= "20261027": print(repr(l))
