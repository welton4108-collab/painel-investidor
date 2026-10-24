#!/usr/bin/env python3
"""
Coletor v1 do painel de Indicadores.
Busca apenas fontes oficiais e gratuitas, calcula percentis e grava
dados/indicadores.json com fonte, data do dado e frequência de cada indicador.

Fontes:
  - Banco Central (SGS e Focus/Olinda)
  - IBGE (SIDRA) — via SGS do BC, que replica o IPCA oficial
  - FRED (Federal Reserve Bank of St. Louis)
  - alternative.me (Fear & Greed de cripto)

Só usa a biblioteca padrão do Python.
"""
import csv, io, json, os, sys, datetime as dt, urllib.request, urllib.parse, statistics, traceback

HOJE = dt.date.today()
SAIDA = os.environ.get("SAIDA_DADOS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados")
FUSO_BR = dt.timezone(dt.timedelta(hours=-3))
os.makedirs(SAIDA, exist_ok=True)
UA = {"User-Agent": "painel-indicadores/1.0 (+contato do site)"}
LOG = []

# Parâmetros editoriais (definidos pelo autor do painel)
JURO_NEUTRO = 5.0   # % a.a., estimativa de juro real neutro usada no ciclo monetário
META_IPCA = 3.0     # % a.a., meta contínua de inflação


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def log(msg):
    LOG.append(msg)
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- utilidades
def pdate(s):
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(s)


def percentil(serie, valor):
    """Fração dos valores históricos menores ou iguais ao valor atual (0 a 1)."""
    vals = [v for v in serie if v is not None]
    if not vals:
        return None
    return round(sum(1 for v in vals if v <= valor) / len(vals), 3)


def faixa(p, baixo="Barato", meio="Na média", alto="Caro"):
    if p is None:
        return None
    return baixo if p < 0.2 else alto if p > 0.8 else meio


def ultimos_anos(pares, anos):
    corte = HOJE - dt.timedelta(days=365 * anos)
    return [(d, v) for d, v in pares if d >= corte]


def amostra(pares, max_pontos=260):
    """Reduz a série para o gráfico, mantendo o último ponto."""
    if len(pares) <= max_pontos:
        return [[d.isoformat(), round(v, 4)] for d, v in pares]
    passo = len(pares) / max_pontos
    idx = sorted(set([int(i * passo) for i in range(max_pontos)] + [len(pares) - 1]))
    return [[pares[i][0].isoformat(), round(pares[i][1], 4)] for i in idx]


# ---------------------------------------------------------------- fontes
def sgs(codigo, anos=10):
    """Série do SGS (Banco Central). Busca em blocos de até 5 anos, porque o SGS
    recusa consultas longas de séries diárias. Um bloco sem dados (o SGS responde
    com uma mensagem em vez de lista) é ignorado; só falha se nada vier."""
    fim_total = HOJE
    ini_total = HOJE - dt.timedelta(days=int(365.25 * anos))
    out, ini, falhas = {}, ini_total, []
    while ini <= fim_total:
        fim = min(fim_total, ini + dt.timedelta(days=365 * 5))
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json"
               f"&dataInicial={urllib.parse.quote(ini.strftime('%d/%m/%Y'))}"
               f"&dataFinal={urllib.parse.quote(fim.strftime('%d/%m/%Y'))}")
        dados = None
        for tentativa in range(3):
            try:
                dados = json.loads(get(url))
                break
            except Exception as e:
                ultimo_erro = e
        if dados is None:
            falhas.append(f"{ini}..{fim}: {ultimo_erro}")
        elif isinstance(dados, list):
            for x in dados:
                if isinstance(x, dict) and x.get("valor") not in (None, ""):
                    out[pdate(x["data"])] = float(x["valor"])
        ini = fim + dt.timedelta(days=1)
    if falhas:
        log(f"aviso SGS {codigo}: blocos sem resposta {falhas}")
    if not out:
        raise RuntimeError(f"SGS {codigo} não retornou dados")
    return sorted(out.items())


def focus(endpoint, filtro, top=1000, orderby="Data desc"):
    """Consulta o Focus (Olinda) em páginas de até 1000 linhas."""
    base = f"https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/{endpoint}"
    out, skip = [], 0
    while len(out) < top:
        n = min(1000, top - len(out))
        q = {"$filter": filtro, "$orderby": orderby, "$top": str(n), "$skip": str(skip), "$format": "json"}
        pagina = json.loads(get(base + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)))["value"]
        out += pagina
        if len(pagina) < n:
            break
        skip += n
    return out


def fred(serie, anos=10):
    """FRED. Com FRED_API_KEY usa a API oficial; sem ela, o CSV público.
    Duas tentativas curtas: se não responder, quem chama usa a fonte alternativa."""
    ini = (HOJE - dt.timedelta(days=int(365.25 * anos))).isoformat()
    chave_api = os.environ.get("FRED_API_KEY")
    ultimo = None
    for tentativa in range(2):
        try:
            if chave_api:
                url = ("https://api.stlouisfed.org/fred/series/observations?"
                       + urllib.parse.urlencode({"series_id": serie, "api_key": chave_api,
                                                 "file_type": "json", "observation_start": ini}))
                obs = json.loads(get(url, timeout=30))["observations"]
                out = [(pdate(o["date"]), float(o["value"])) for o in obs if o["value"] not in (".", "")]
            else:
                txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}&cosd={ini}", timeout=30)
                out = []
                for row in csv.DictReader(io.StringIO(txt)):
                    chave = [k for k in row if k.upper() not in ("OBSERVATION_DATE", "DATE")][0]
                    dk = "observation_date" if "observation_date" in row else "DATE"
                    if row[chave] not in (".", ""):
                        out.append((pdate(row[dk]), float(row[chave])))
            if out:
                return out
        except Exception as e:
            ultimo = e
    raise RuntimeError(f"FRED {serie} sem resposta: {ultimo}")


def cboe(indice, anos=10):
    """Histórico diário oficial da Cboe (VIX, VXEWZ). Usa a última coluna (fechamento)."""
    txt = get(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{indice}_History.csv", timeout=40)
    corte = HOJE - dt.timedelta(days=int(365.25 * anos))
    out = []
    for row in csv.reader(io.StringIO(txt)):
        if not row or not row[0][:1].isdigit():
            continue
        try:
            d = pdate(row[0].strip())
            v = float(row[-1])
        except ValueError:
            continue
        if d >= corte:
            out.append((d, v))
    if not out:
        raise RuntimeError(f"Cboe {indice} vazio")
    return sorted(out)


def tesouro_eua(tipo, coluna, anos=10):
    """Curvas diárias do Tesouro americano (home.treasury.gov), um arquivo por ano."""
    out = {}
    for ano in range(HOJE.year - anos, HOJE.year + 1):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{ano}/all?type={tipo}&field_tdr_date_value={ano}&page&_format=csv")
        try:
            txt = get(url, timeout=40)
        except Exception as e:
            log(f"aviso Tesouro EUA {ano}: {e}")
            continue
        leitor = csv.DictReader(io.StringIO(txt))
        col = next((c for c in (leitor.fieldnames or []) if c.strip().upper() == coluna.upper()), None)
        if not col:
            continue
        for row in leitor:
            try:
                out[pdate(row["Date"].strip())] = float(row[col])
            except (ValueError, KeyError):
                pass
    if not out:
        raise RuntimeError(f"Tesouro EUA {tipo} vazio")
    return sorted(out.items())


def coinbase_btc(anos=12):
    """Fechamento diário do BTC-USD na Coinbase, em blocos de 300 dias."""
    out = {}
    fim = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    ini_total = fim - dt.timedelta(days=int(365.25 * anos))
    ini = ini_total
    while ini < fim:
        bloco_fim = min(fim, ini + dt.timedelta(days=299))
        url = ("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400"
               f"&start={ini.strftime('%Y-%m-%dT%H:%M:%SZ')}&end={bloco_fim.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        for c in json.loads(get(url, timeout=40)):
            out[dt.datetime.fromtimestamp(c[0], dt.timezone.utc).date()] = float(c[4])
        ini = bloco_fim + dt.timedelta(days=1)
    if not out:
        raise RuntimeError("Coinbase sem dados")
    return sorted(out.items())


def com_alternativa(nome, principal, alternativa, rotulo_principal, rotulo_alt):
    """Tenta a fonte principal; se falhar, usa a alternativa e registra qual foi usada."""
    try:
        return principal(), rotulo_principal
    except Exception as e:
        log(f"aviso {nome}: {rotulo_principal} falhou ({e}); usando {rotulo_alt}")
        return alternativa(), rotulo_alt


# ---------------------------------------------------------------- indicadores
IND = {}


def registrar(chave, fn):
    try:
        IND[chave] = fn()
        log(f"ok   {chave}")
    except Exception as e:  # um indicador com erro não derruba os outros
        log(f"ERRO {chave}: {e}")
        traceback.print_exc()
        IND[chave] = {"erro": str(e)}


def ind_inflacao():
    ipca12 = sgs(13522, anos=10)          # IPCA acumulado 12 meses (IBGE, via BC)
    d, v = ipca12[-1]
    f12 = focus("ExpectativasMercadoInflacao12Meses",
                "Indicador eq 'IPCA' and Suavizada eq 'S' and baseCalculo eq 0", top=4000)
    f12s = sorted([(pdate(x["Data"]), x["Mediana"]) for x in f12])
    anual = focus("ExpectativasMercadoAnuais", "Indicador eq 'IPCA' and baseCalculo eq 0", top=60)
    ultima = max(pdate(x["Data"]) for x in anual)
    por_ano = {int(x["DataReferencia"]): x["Mediana"] for x in anual if pdate(x["Data"]) == ultima}
    return {
        "titulo": "Inflação: realizada × esperada",
        "realizado": {"valor": v, "data": d.isoformat(), "rotulo": "IPCA 12 meses"},
        "esperado_12m": {"valor": f12s[-1][1], "data": f12s[-1][0].isoformat()},
        "focus_anos": por_ano,
        "focus_data": ultima.isoformat(),
        "meta": META_IPCA,
        "hist_realizado": amostra(ultimos_anos(ipca12, 10)),
        "hist_esperado": amostra(ultimos_anos(f12s, 10)),
        "fonte": "IBGE (IPCA, via SGS do Banco Central) e Boletim Focus (Banco Central)",
        "freq": "IPCA: mensal, por volta do dia 10. Focus: semanal, às segundas.",
    }


def ind_selic():
    selic = sgs(432, anos=10)              # meta Selic
    d, v = selic[-1]
    reun = focus("ExpectativasMercadoSelic", "baseCalculo eq 0", top=200)
    ultima = max(pdate(x["Data"]) for x in reun)
    caminho = sorted([(x["Reuniao"], x["Mediana"]) for x in reun if pdate(x["Data"]) == ultima],
                     key=lambda r: (int(r[0].split("/")[1]), int(r[0].split("/")[0][1:])))
    return {
        "titulo": "Selic: atual × esperada pelo Focus",
        "atual": {"valor": v, "data": d.isoformat()},
        "caminho_focus": caminho,
        "focus_data": ultima.isoformat(),
        "hist": amostra(ultimos_anos(selic, 10)),
        "fonte": "Banco Central (meta Selic, SGS 432) e Boletim Focus por reunião do Copom",
        "freq": "Selic: a cada reunião do Copom. Focus: semanal, às segundas.",
    }


def ind_ciclo(inf, sel):
    """Juro real ex-ante = Selic esperada em ~12 meses descontada do IPCA esperado em 12 meses."""
    alvo = HOJE + dt.timedelta(days=365)
    # aproxima a reunião mais próxima de 12 meses: 8 reuniões por ano, R1..R8
    melhor = None
    for r, m in sel["caminho_focus"]:
        n, ano = r.split("/")
        mes = round((int(n[1:]) - 1) * 12 / 8) + 1
        d = dt.date(int(ano), mes, 15)
        dist = abs((d - alvo).days)
        if melhor is None or dist < melhor[0]:
            melhor = (dist, r, m)
    selic12 = melhor[2] if melhor else sel["atual"]["valor"]
    ipca12 = inf["esperado_12m"]["valor"]
    real = ((1 + selic12 / 100) / (1 + ipca12 / 100) - 1) * 100
    gap = real - JURO_NEUTRO
    estado = "Restritivo" if gap > 1 else "Estimulativo" if gap < -1 else "Neutro"
    atual, futura = sel["atual"]["valor"], selic12
    direcao = "Cortes à frente" if futura < atual - 0.25 else "Altas à frente" if futura > atual + 0.25 else "Estabilidade"
    return {
        "titulo": "Ciclo de política monetária",
        "juro_real_exante": round(real, 2),
        "juro_neutro": JURO_NEUTRO,
        "gap": round(gap, 2),
        "estado": estado,
        "direcao": direcao,
        "selic_12m": selic12, "reuniao_12m": melhor[1] if melhor else None,
        "ipca_12m": ipca12,
        "fonte": "Boletim Focus (Selic por reunião e IPCA 12 meses). Juro neutro: parâmetro do painel",
        "freq": "Semanal, às segundas.",
    }


def ind_cambio():
    ptax = sgs(1, anos=10)                 # dólar PTAX venda
    reer = sgs(11752, anos=20)             # taxa de câmbio efetiva real (IPCA), mensal
    d, v = ptax[-1]
    dr, vr = reer[-1]
    base10 = [x for _, x in ultimos_anos(reer, 10)]
    media10 = statistics.mean(base10)
    p = percentil(base10, vr)
    # índice maior = real mais desvalorizado (dólar "caro" em termos reais)
    leitura = "Dólar caro / real barato" if p > 0.8 else "Dólar barato / real caro" if p < 0.2 else "Câmbio perto da média"
    return {
        "titulo": "Câmbio",
        "ptax": {"valor": v, "data": d.isoformat()},
        "real_efetivo": {"valor": vr, "data": dr.isoformat(), "media_10a": round(media10, 2),
                          "desvio_pct": round((vr / media10 - 1) * 100, 1), "percentil": p, "leitura": leitura},
        "hist_ptax": amostra(ultimos_anos(ptax, 5)),
        "hist_real": amostra(ultimos_anos(reer, 10)),
        "fonte": "Banco Central: PTAX (SGS 1) e índice de taxa de câmbio efetiva real (SGS 11752)",
        "freq": "PTAX: diária, por volta das 13h. Câmbio real: mensal, com cerca de 1 mês de atraso.",
    }


def ind_eua():
    vix, f1 = com_alternativa("VIX", lambda: fred("VIXCLS", 10), lambda: cboe("VIX", 10), "FRED", "Cboe")
    vxewz, f2 = com_alternativa("VXEWZ", lambda: fred("VXEWZCLS", 10), lambda: cboe("VXEWZ", 10), "FRED", "Cboe")
    def curva_tesouro():
        n10 = dict(tesouro_eua("daily_treasury_yield_curve", "10 Yr", 10))
        n2 = dict(tesouro_eua("daily_treasury_yield_curve", "2 Yr", 10))
        return sorted((d, round(n10[d] - n2[d], 2)) for d in n10 if d in n2)
    curva, f3 = com_alternativa("curva", lambda: fred("T10Y2Y", 10), curva_tesouro, "FRED", "Tesouro dos EUA")
    real10, f4 = com_alternativa("juro real", lambda: fred("DFII10", 10),
                                 lambda: tesouro_eua("daily_treasury_real_yield_curve", "10 YR", 10),
                                 "FRED", "Tesouro dos EUA")
    usadas = sorted(set([f1, f2, f3, f4]))
    def pack(s, nome, leitura_fn):
        d, v = s[-1]
        p = percentil([x for _, x in s], v)
        return {"nome": nome, "valor": v, "data": d.isoformat(), "percentil": p,
                "leitura": leitura_fn(v, p), "hist": amostra(ultimos_anos(s, 5))}
    return {
        "titulo": "Estados Unidos e medo global",
        "vix": pack(vix, "VIX (medo no S&P 500)",
                    lambda v, p: "Medo alto" if p > 0.8 else "Complacência" if p < 0.2 else "Normal"),
        "curva": pack(curva, "Curva de juros 10a − 2a",
                      lambda v, p: "Invertida (alerta de recessão)" if v < 0 else "Positiva"),
        "juro_real_10a": pack(real10, "Juro real do Tesouro americano 10 anos",
                              lambda v, p: "Alto" if p > 0.8 else "Baixo" if p < 0.2 else "Na média"),
        "vxewz": pack(vxewz, "VXEWZ (medo na bolsa brasileira)",
                      lambda v, p: "Medo alto" if p > 0.8 else "Complacência" if p < 0.2 else "Normal"),
        "fonte": "Índices VIX e VXEWZ da Cboe; curva e juro real do Tesouro dos EUA (via " + ", ".join(usadas) + ")",
        "freq": "Diária, com 1 dia útil de atraso.",
    }


def ind_bitcoin():
    btc, fb = com_alternativa("bitcoin", lambda: fred("CBBTCUSD", 12), lambda: coinbase_btc(12), "FRED", "Coinbase")
    if len(btc) < 400:
        raise RuntimeError("série de bitcoin curta demais")
    mm, mayer = [], []
    for i in range(199, len(btc)):
        janela = [v for _, v in btc[i - 199:i + 1]]
        m = sum(janela) / 200
        mayer.append((btc[i][0], btc[i][1] / m))
    d, v = btc[-1]
    mv = mayer[-1][1]
    p = percentil([x for _, x in mayer], mv)
    leitura = "Euforia" if mv > 2.4 else "Barato historicamente" if mv < 1 else "Na média"
    fg = None
    try:
        j = json.loads(get("https://api.alternative.me/fng/?limit=1"))["data"][0]
        fg = {"valor": int(j["value"]), "classe": j["value_classification"],
              "data": dt.datetime.fromtimestamp(int(j["timestamp"]), dt.timezone.utc).date().isoformat()}
    except Exception as e:
        log(f"aviso fear&greed: {e}")
    return {
        "titulo": "Bitcoin",
        "preco": {"valor": v, "data": d.isoformat()},
        "mayer": {"valor": round(mv, 2), "percentil": p, "leitura": leitura},
        "hist_mayer": amostra(ultimos_anos(mayer, 8)),
        "fear_greed": fg,
        "fonte": f"Preço BTC-USD da Coinbase (via {fb}). Fear & Greed: alternative.me",
        "freq": "Diária.",
    }


def main():
    caminho = os.path.join(SAIDA, "indicadores.json")
    anterior = {}
    try:
        with open(caminho, encoding="utf-8") as f:
            anterior = json.load(f).get("indicadores", {})
    except Exception:
        pass

    registrar("inflacao", ind_inflacao)
    registrar("selic", ind_selic)
    if "erro" not in IND.get("inflacao", {"erro": 1}) and "erro" not in IND.get("selic", {"erro": 1}):
        registrar("ciclo", lambda: ind_ciclo(IND["inflacao"], IND["selic"]))
    registrar("cambio", ind_cambio)
    registrar("eua", ind_eua)
    registrar("bitcoin", ind_bitcoin)

    # Fonte fora do ar: mantém o último dado válido e marca como desatualizado.
    erros = {}
    for k in ("inflacao", "selic", "ciclo", "cambio", "eua", "bitcoin"):
        atual = IND.get(k)
        if atual is None or "erro" in atual:
            erros[k] = (atual or {}).get("erro", "não coletado")
            prev = anterior.get(k)
            if prev and "erro" not in prev:
                prev = dict(prev)
                prev["desatualizado"] = True
                IND[k] = prev
                log(f"mantido último dado válido de {k}")

    out = {"gerado_em": dt.datetime.now(FUSO_BR).strftime("%Y-%m-%dT%H:%M"), "indicadores": IND, "log": LOG}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": [k for k in IND if k not in erros], "erro": erros}, ensure_ascii=False))
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
