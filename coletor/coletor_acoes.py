#!/usr/bin/env python3
"""
Coletor de indicadores de ações da B3 a partir de fontes oficiais e gratuitas.

- Demonstrações financeiras: CVM Dados Abertos (ITR trimestral e DFP anual), licença ODbL.
- Cadastro e setor: CVM (cad_cia_aberta) e códigos de negociação: CVM FCA (valor mobiliário).
- Preço e liquidez: B3, arquivo anual de cotações históricas (COTAHIST), atraso de 1 dia útil.

Gera dados/acoes.json. Só usa a biblioteca padrão do Python.
"""
import csv, io, json, os, re, sys, time, zipfile, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, os.environ.get("SAIDA_DADOS", "dados"), "acoes.json")
CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
UA = {"User-Agent": "Mozilla/5.0 (painel-investidor; coleta de dados publicos)"}
HOJE = date.today()
LOG = []


def log(msg):
    print(msg, flush=True); LOG.append(msg)


def baixar(url, tentativas=3):
    for i in range(tentativas):
        try:
            t = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                b = r.read()
            log(f"ok   {url.rsplit('/', 1)[-1]} ({len(b)/1e6:.1f} MB, {time.time()-t:.0f}s)")
            return b
        except Exception as e:
            if i == tentativas - 1:
                log(f"erro {url}: {e}")
                return None
            time.sleep(5 * (i + 1))


def csv_zip(z, nome):
    try:
        txt = z.read(nome).decode("latin-1")
    except KeyError:
        return []
    return csv.DictReader(io.StringIO(txt), delimiter=";")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ------------------------------------------------------------------ demonstrações

class Demos:
    """Guarda demonstrações por CNPJ e data de referência (só a última versão), em tuplas enxutas."""

    def __init__(self, cnpjs):
        self.cnpjs = cnpjs
        # dados[cnpj][dt_refer][tipo] = (escopo, [(cd, ds, valor, ordem, ini, fim)])
        self.dados = defaultdict(lambda: defaultdict(dict))
        self.cap = {}  # cnpj -> (dt_refer, on, pn)

    def carregar(self, z, prefixo, ano, tipos=("DRE", "BPA", "BPP", "DFC_MI")):
        for tipo in tipos:
            for escopo in ("con", "ind"):
                linhas, versao = {}, {}
                for r in csv_zip(z, f"{prefixo}_{tipo}_{escopo}_{ano}.csv"):
                    if r["CNPJ_CIA"] not in self.cnpjs:
                        continue
                    k = (r["CNPJ_CIA"], r["DT_REFER"])
                    v = int(r["VERSAO"] or 0)
                    if v > versao.get(k, -1):
                        versao[k] = v; linhas[k] = []
                    if v == versao[k]:
                        esc = 1000.0 if r.get("ESCALA_MOEDA", "").upper() == "MIL" else 1.0
                        linhas[k].append((r["CD_CONTA"], r["DS_CONTA"], (num(r["VL_CONTA"]) or 0) * esc,
                                          r["ORDEM_EXERC"], r.get("DT_INI_EXERC", ""), r.get("DT_FIM_EXERC", "")))
                for (cnpj, dt), rows in linhas.items():
                    atual = self.dados[cnpj][dt].get(tipo)
                    # consolidado tem prioridade sobre individual
                    if atual is None or (escopo == "con" and atual[0] == "ind"):
                        self.dados[cnpj][dt][tipo] = (escopo, rows)
        versao = {}
        for r in csv_zip(z, f"{prefixo}_composicao_capital_{ano}.csv"):
            cnpj, dt, v = r["CNPJ_CIA"], r["DT_REFER"], int(r["VERSAO"] or 0)
            if cnpj not in self.cnpjs or (dt, v) <= versao.get(cnpj, ("", -1)):
                continue
            on = (num(r["QT_ACAO_ORDIN_CAP_INTEGR"]) or 0) - (num(r["QT_ACAO_ORDIN_TESOURO"]) or 0)
            pn = (num(r["QT_ACAO_PREF_CAP_INTEGR"]) or 0) - (num(r["QT_ACAO_PREF_TESOURO"]) or 0)
            if on + pn > 0:
                versao[cnpj] = (dt, v)
                if cnpj not in self.cap or dt >= self.cap[cnpj][0]:
                    self.cap[cnpj] = (dt, on, pn)

    def linhas(self, cnpj, dt, tipo):
        x = self.dados.get(cnpj, {}).get(dt, {}).get(tipo)
        return x[1] if x else []


def periodos(rows, ordem):
    """Agrupa linhas de fluxo (DRE/DFC) por (dt_ini, dt_fim)."""
    out = defaultdict(dict)
    for cd, ds, v, o, ini, fim in rows:
        if o == ordem:
            out[(ini, fim)][cd] = (ds, v)
    return out


def saldo(rows, ordem="ÚLTIMO"):
    return {cd: (ds, v) for cd, ds, v, o, ini, fim in rows if o == ordem}


def nivel(cd):
    return cd.count(".") + 1


# ---- extração de contas (por descrição, para valer em vários layouts)

def lucro_controladores(c):
    """Lucro líquido atribuído aos controladores (ou o lucro do período)."""
    cand = [cd for cd, (ds, _) in c.items() if nivel(cd) == 2 and cd.startswith("3.")
            and re.search(r"lucro.*(per[ií]odo|exerc[ií]cio)", ds, re.I) and not re.search(r"opera[çc][õo]es (continuadas|descontinuadas)|por a[çc][ãa]o|antes", ds, re.I)]
    if not cand:
        return None
    cd = sorted(cand)[-1]
    for f, (ds, v) in c.items():
        if f.startswith(cd + ".") and nivel(f) == 3 and re.search(r"controladora", ds, re.I) and not re.search(r"n[ãa]o controlador", ds, re.I):
            return v
    return c[cd][1]


def conta_ds(c, prefixo, padrao, niv=None):
    for cd, (ds, v) in c.items():
        if cd.startswith(prefixo) and (niv is None or nivel(cd) == niv) and re.search(padrao, ds, re.I):
            return v
    return None


def ebit(c):
    return conta_ds(c, "3.", r"^resultado antes do resultado financeiro", 2)


def receita(c):
    v = c.get("3.01")
    return v[1] if v else None


def deprec(c):
    tot, achou = 0.0, False
    for cd, (ds, v) in c.items():
        if cd.startswith("6.01.01.") and nivel(cd) == 4 and re.search(r"deprecia|amortiza|exaust|deple", ds, re.I) and not re.search(r"juros|debentur|empr[ée]stimo|financiamento|custo de transa", ds, re.I):
            tot += abs(v); achou = True
    return tot if achou else None


def proventos(c):
    tot = 0.0
    for cd, (ds, v) in c.items():
        if cd.startswith("6.03.") and nivel(cd) == 3 and re.search(r"dividendo|juros sobre (o )?capital", ds, re.I) and not re.search(r"n[ãa]o controlador|recebid", ds, re.I) and v < 0:
            tot += -v
    return tot


# ---- fluxo dos últimos 12 meses

def ltm(dm, cnpj, fn, tipo):
    """Valor dos últimos 12 meses para uma conta de fluxo (DRE ou DFC)."""
    datas = sorted(dm.dados.get(cnpj, {}).keys())
    datas = [x for x in datas if tipo in dm.dados[cnpj][x]]
    if not datas:
        return None, None
    ult = datas[-1]
    rows = dm.linhas(cnpj, ult, tipo)
    cur = periodos(rows, "ÚLTIMO")
    if not cur:
        return None, None
    ini_cur = min(k[0] for k in cur)            # período acumulado do ano
    acum = cur[(ini_cur, ult)] if (ini_cur, ult) in cur else None
    if acum is None:
        return None, None
    v_acum = fn(acum)
    if v_acum is None:
        return None, None
    dias = (d(ult) - d(ini_cur)).days
    if dias >= 360:                             # já é um exercício completo
        return v_acum, ult
    prev = periodos(rows, "PENÚLTIMO")
    if not prev:
        return None, None
    ini_prev = min(k[0] for k in prev)
    fim_prev = max(k[1] for k in prev if k[0] == ini_prev)
    v_prev = fn(prev[(ini_prev, fim_prev)])
    # exercício anterior completo (DFP com fim no dia anterior ao início do ano corrente)
    fim_fy = (d(ini_cur) - timedelta(days=1)).isoformat()
    fy_rows = dm.linhas(cnpj, fim_fy, tipo)
    fy = periodos(fy_rows, "ÚLTIMO")
    v_fy = None
    for (a, b), c in fy.items():
        if b == fim_fy and (d(b) - d(a)).days >= 360:
            v_fy = fn(c)
    if v_fy is None or v_prev is None:
        return None, None
    return v_fy + v_acum - v_prev, ult


def anual(dm, cnpj, fim, fn, tipo="DRE"):
    """Valor de um exercício fechado em `fim` (procura no DFP do ano ou do ano seguinte)."""
    for dt in (fim, (d(fim).replace(year=d(fim).year + 1)).isoformat()):
        rows = dm.linhas(cnpj, dt, tipo)
        for ordem in ("ÚLTIMO", "PENÚLTIMO"):
            for (a, b), c in periodos(rows, ordem).items():
                if b == fim and (d(b) - d(a)).days >= 360:
                    v = fn(c)
                    if v is not None:
                        return v
    return None


# ------------------------------------------------------------------ B3

def cotacoes(anos):
    """Lê o COTAHIST: último preço e volume diário de ações do mercado à vista (lote padrão)."""
    hist = defaultdict(list)  # ticker -> [(data, preço, volume)]
    for ano in anos:
        b = baixar(f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP")
        if not b:
            continue
        z = zipfile.ZipFile(io.BytesIO(b))
        with z.open(z.namelist()[0]) as f:
            for linha in io.TextIOWrapper(f, encoding="latin-1"):
                if not linha.startswith("01") or linha[10:12] != "02" or linha[24:27] != "010":
                    continue
                tk = linha[12:24].strip()
                fat = int(linha[210:217] or 1) or 1
                preco = int(linha[108:121]) / 100 / fat
                vol = int(linha[170:188]) / 100
                hist[tk].append((linha[2:10], preco, vol))
    return hist


# ------------------------------------------------------------------ principal

FINANCEIRO = re.compile(r"banco|intermedia[çc][ãa]o financeira|seguradora|securitiza|arrendamento|cr[ée]dito", re.I)


def main():
    ano = HOJE.year
    cad = baixar(f"{CVM}/CAD/DADOS/cad_cia_aberta.csv")
    if not cad:
        sys.exit(1)
    empresas = {}
    for r in csv.DictReader(io.StringIO(cad.decode("latin-1")), delimiter=";"):
        if r["SIT"] == "ATIVO":
            atual = empresas.get(r["CNPJ_CIA"])
            if not atual or r["TP_MERC"] == "BOLSA":
                empresas[r["CNPJ_CIA"]] = r

    # códigos de negociação (FCA do ano; o do ano anterior completa quem ainda não entregou)
    tickers = defaultdict(dict)  # cnpj -> ticker -> classe
    for a in (ano - 1, ano):
        b = baixar(f"{CVM}/DOC/FCA/DADOS/fca_cia_aberta_{a}.zip")
        if not b:
            continue
        z = zipfile.ZipFile(io.BytesIO(b))
        for r in csv_zip(z, f"fca_cia_aberta_valor_mobiliario_{a}.csv"):
            tk = (r["Codigo_Negociacao"] or "").strip().upper()
            vm = r["Valor_Mobiliario"]
            if not tk or r["Mercado"] != "Bolsa" or r["Data_Fim_Negociacao"]:
                continue
            if vm.startswith("Ações Ordinárias"):
                tickers[r["CNPJ_Companhia"]][tk] = "ON"
            elif vm.startswith("Ações Preferenciais"):
                tickers[r["CNPJ_Companhia"]][tk] = "PN"
            elif vm.startswith("Units") or vm.startswith("Certificado"):
                tickers[r["CNPJ_Companhia"]][tk] = "UNT"

    dm = Demos(set(tickers))
    for tipo, a in (("dfp", ano - 6), ("dfp", ano - 5), ("dfp", ano - 2), ("dfp", ano - 1), ("itr", ano - 1), ("itr", ano)):
        b = baixar(f"{CVM}/DOC/{tipo.upper()}/DADOS/{tipo}_cia_aberta_{a}.zip")
        if b:
            # anos antigos só servem para o crescimento do lucro
            tipos = ("DRE",) if a <= ano - 5 else ("DRE", "BPA", "BPP", "DFC_MI")
            dm.carregar(zipfile.ZipFile(io.BytesIO(b)), f"{tipo}_cia_aberta", a, tipos)
            del b

    hist = cotacoes([ano - 1, ano] if HOJE.month <= 3 else [ano])
    ultimo_pregao = max((v[-1][0] for v in hist.values() if v), default="")
    limite = (datetime.strptime(ultimo_pregao, "%Y%m%d").date() - timedelta(days=20)).strftime("%Y%m%d") if ultimo_pregao else ""

    def mercado(tk):
        h = hist.get(tk)
        if not h or h[-1][0] < limite:
            return None
        h = sorted(h)
        jan = h[-42:]  # cerca de 2 meses de pregões
        return {"preco": h[-1][1], "data": h[-1][0], "liq": sum(x[2] for x in jan) / len(jan)}

    linhas, sem_dados = [], 0
    for cnpj, tks in tickers.items():
        cad_r = empresas.get(cnpj)
        if not cad_r:
            continue
        mk = {tk: mercado(tk) for tk in tks}
        mk = {tk: m for tk, m in mk.items() if m}
        if not mk:
            continue
        principal = max(mk, key=lambda t: mk[t]["liq"])
        setor_cvm = cad_r["SETOR_ATIV"] or ""
        setor = re.sub(r"^Emp\. Adm\. Part\. - ", "", setor_cvm).strip() or "Sem setor"
        fin = bool(FINANCEIRO.search(setor_cvm))

        # valor de mercado: ações ON e PN em circulação x preço da classe mais líquida
        cap = dm.cap.get(cnpj)
        vm = None
        if cap:
            _, on, pn = cap
            def preco_classe(cl):
                c = [t for t in mk if tks[t] == cl]
                return mk[max(c, key=lambda t: mk[t]["liq"])]["preco"] if c else None
            p_on, p_pn = preco_classe("ON"), preco_classe("PN")
            p_ref = mk[principal]["preco"] if tks[principal] != "UNT" else None
            p_on = p_on or p_pn or p_ref
            p_pn = p_pn or p_on or p_ref
            if p_on or p_pn:
                vm = on * (p_on or 0) + pn * (p_pn or 0)

        lucro, dt_b = ltm(dm, cnpj, lucro_controladores, "DRE")
        rec, _ = (None, None) if fin else ltm(dm, cnpj, receita, "DRE")
        eb, _ = (None, None) if fin else ltm(dm, cnpj, ebit, "DRE")
        da, _ = (None, None) if fin else ltm(dm, cnpj, deprec, "DFC_MI")
        prov, _ = ltm(dm, cnpj, proventos, "DFC_MI")
        ebitda = eb + da if (eb is not None and da is not None) else None

        # balanço mais recente
        datas = sorted(x for x in dm.dados.get(cnpj, {}) if "BPP" in dm.dados[cnpj][x])
        pl = div_liq = None
        if datas:
            bpa, bpp = saldo(dm.linhas(cnpj, datas[-1], "BPA")), saldo(dm.linhas(cnpj, datas[-1], "BPP"))
            cd_pl = next((cd for cd, (ds, v) in bpp.items() if nivel(cd) == 2 and re.search(r"^patrim[ôo]nio l[íi]quido", ds, re.I)), None)
            pl_tot = bpp[cd_pl][1] if cd_pl else None
            minor = conta_ds(bpp, (cd_pl or "x") + ".", r"n[ãa]o controlador", 3) or 0
            pl = pl_tot - minor if pl_tot is not None else None
            if not fin:
                divida = sum(v for cd, (ds, v) in bpp.items() if nivel(cd) == 3 and cd[:4] in ("2.01", "2.02") and re.search(r"^empr[ée]stimos e financiamentos", ds, re.I))
                caixa = sum(v for cd, (ds, v) in bpa.items() if nivel(cd) == 3 and cd.startswith("1.01.") and re.search(r"^caixa e equivalentes|^aplica[çc][õo]es financeiras", ds, re.I))
                div_liq = divida - caixa

        # crescimento do lucro em 5 anos (exercícios fechados)
        cagr = None
        fim_ult = f"{ano - 1}-12-31"
        l1, l0 = anual(dm, cnpj, fim_ult, lucro_controladores), anual(dm, cnpj, f"{ano - 6}-12-31", lucro_controladores)
        if l1 and l0 and l1 > 0 and l0 > 0:
            cagr = (l1 / l0) ** (1 / 5) - 1

        def div(a, b, pos=True):
            if a is None or b is None or b == 0 or (pos and b < 0):
                return None
            return a / b

        ev = vm + div_liq if (vm is not None and div_liq is not None) else None
        reg = {
            "tk": principal, "outros": sorted(t for t in mk if t != principal),
            "nome": (cad_r["DENOM_COMERC"] or cad_r["DENOM_SOCIAL"]).title()[:40],
            "setor": setor, "fin": fin,
            "preco": round(mk[principal]["preco"], 2), "liq": round(mk[principal]["liq"]),
            "vm": round(vm) if vm else None,
            "lucro": round(lucro) if lucro is not None else None,
            "ebitda": round(ebitda) if ebitda is not None else None,
            "div_liq": round(div_liq) if div_liq is not None else None,
            "pl": round(pl) if pl is not None else None,
            "p_l": div(vm, lucro), "p_vp": div(vm, pl), "ev_ebitda": div(ev, ebitda), "ev_ebit": div(ev, eb),
            "dy": div(prov, vm) if prov else (0.0 if prov == 0 and vm else None),
            "roe": div(lucro, pl), "m_ebitda": div(ebitda, rec), "m_liq": div(lucro, rec),
            "dl_ebitda": div(div_liq, ebitda), "cagr5": cagr,
            "balanco": dt_b,
        }
        for k in ("p_l", "p_vp", "ev_ebitda", "ev_ebit", "dy", "roe", "m_ebitda", "m_liq", "dl_ebitda", "cagr5"):
            if reg[k] is not None:
                reg[k] = round(reg[k], 4)
        if lucro is None:
            sem_dados += 1
        linhas.append(reg)

    linhas.sort(key=lambda r: -(r["vm"] or 0))
    # diagnóstico: contas de referência de algumas empresas, para conferir o mapeamento
    for r in linhas:
        if r["tk"] in ("PETR4", "VALE3", "ITUB4", "WEGE3", "BBSE3", "BBAS3"):
            log("DIAG " + json.dumps(r, ensure_ascii=False))
    for r in linhas:
        if r["tk"] in ("ITUB4", "BBSE3"):
            cnpj = next(c for c, t in tickers.items() if r["tk"] in t)
            ult = sorted(x for x in dm.dados[cnpj] if "DRE" in dm.dados[cnpj][x])[-1]
            for cd, ds, v, o, ini, fim in dm.linhas(cnpj, ult, "DRE"):
                if o == "ÚLTIMO" and nivel(cd) <= 3:
                    log(f"DRE {r['tk']} {ini}..{fim} {cd} {ds} {v:,.0f}")
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({"gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M"), "pregao": ultimo_pregao,
                   "fonte": "Demonstrações: CVM Dados Abertos (ITR e DFP). Preço e liquidez: B3, cotações históricas.",
                   "acoes": linhas}, f, ensure_ascii=False, separators=(",", ":"))
    log(f"{len(linhas)} empresas; {sem_dados} sem lucro calculado; pregão {ultimo_pregao}")
    with open(os.path.join(os.path.dirname(SAIDA), "acoes_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    if len(linhas) < 100:
        sys.exit(1)


if __name__ == "__main__":
    main()
