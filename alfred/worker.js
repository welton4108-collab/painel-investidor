/**
 * Alfred: intermediário seguro entre a página do chat e a API da Anthropic.
 * Roda como Cloudflare Worker. A chave da API fica guardada no Cloudflare
 * (segredo ANTHROPIC_API_KEY) e nunca chega ao navegador do visitante.
 *
 * Configuração no painel do Cloudflare (Worker > Settings):
 *   Segredos (Variables and Secrets, tipo Secret):
 *     ANTHROPIC_API_KEY  chave da API, criada em console.anthropic.com
 *     ACCESS_CODE        código de acesso da versão de teste (apague para abrir ao público)
 *   Ligação (Bindings > KV namespace):
 *     LIMITES            namespace KV usado para os limites de uso
 *   Variáveis opcionais (tipo Text):
 *     MODELO             padrão claude-sonnet-5-5
 *     LIMITE_IP_HORA     mensagens por visitante por hora, padrão 40
 *     LIMITE_DIA         mensagens no total por dia, padrão 300
 *     ORIGENS            sites autorizados, separados por vírgula
 */

const SITE = "https://painel.objetivoprimeiro.com";
const ORIGENS_PADRAO = [SITE];
const LEADS_URL = "https://script.google.com/macros/s/AKfycbyKDNfPPI7u0yieLIwe61DyFEZy3To4ye5m2exLEKYUnBRK3lGd3Mw-t10PjWGAGcgs/exec";
const MAX_MENSAGENS = 24;      // histórico enviado ao modelo (a coleta de informações usa várias trocas)
const MAX_CARACTERES = 2000;   // por mensagem do visitante
const MAX_TOKENS = 1500;       // teto da resposta (o Raio-X é a mais longa); o tom curto vem das instruções
const CACHE_SEG = 600;         // instruções e dados ficam 10 min em memória

let memoria = { instrucoes: null, dados: null, em: 0 };

// Busca na web restrita a fontes oficiais, no máximo 2 buscas por resposta (US$ 10 a cada 1.000 buscas).
const BUSCA = {
  type: "web_search_20250305",
  name: "web_search",
  max_uses: 2,
  allowed_domains: ["gov.br", "bcb.gov.br", "tesourodireto.com.br", "b3.com.br", "anbima.com.br",
                    "fgc.org.br", "planejar.org.br", "ibge.gov.br", "cvm.gov.br"],
  user_location: { type: "approximate", country: "BR", timezone: "America/Sao_Paulo" },
};

// Calculadoras com as mesmas fórmulas do Simulador do painel (valores em reais de hoje, juros reais).
const PERFIS = { conservadora: 3, moderada: 4.5, arrojada: 6 };
const CALCULADORAS = [
  {
    name: "calcular_aposentadoria",
    description: "Contas de aposentadoria com as premissas do Simulador do painel: rendimento real da carteira (conservadora 3%, moderada 4,5%, arrojada 6% ao ano acima da inflação) até a idade da renda; na fase de renda, 4% ao ano ou o rendimento da carteira, o que for menor; renda até os 99 anos. Informe renda_mensal para saber o patrimônio e o aporte necessários; informe aporte_mensal para saber o patrimônio projetado e a renda possível. Valores em reais de hoje.",
    input_schema: {
      type: "object",
      properties: {
        idade_atual: { type: "number" },
        idade_renda: { type: "number", description: "Idade em que a renda começa." },
        perfil: { type: "string", enum: ["conservadora", "moderada", "arrojada"], description: "Padrão: moderada." },
        patrimonio_atual: { type: "number", description: "Já investido para este objetivo, em reais. Padrão 0." },
        renda_mensal: { type: "number", description: "Renda mensal desejada, em reais de hoje." },
        aporte_mensal: { type: "number", description: "Quanto consegue investir por mês, em reais." },
      },
      required: ["idade_atual", "idade_renda"],
    },
  },
  {
    name: "calcular_meta",
    description: "Juros compostos mensais com rendimento real (padrão 4,5% ao ano acima da inflação; use 0 para dinheiro parado). Informe dois entre meta, aporte_mensal e meses para obter o terceiro, ou só aporte_mensal e meses para o valor acumulado. Serve para reserva de emergência, metas de médio prazo, viagem, educação e efeito de cortar gastos.",
    input_schema: {
      type: "object",
      properties: {
        meta: { type: "number", description: "Valor a juntar, em reais de hoje." },
        aporte_mensal: { type: "number" },
        meses: { type: "number" },
        inicial: { type: "number", description: "Valor já guardado. Padrão 0." },
        rendimento_real_anual: { type: "number", description: "Em %, padrão 4,5." },
      },
    },
  },
];

const taxaMes = r => Math.pow(1 + r / 100, 1 / 12) - 1;
const fv = (ini, pmt, n, i) => n <= 0 ? ini : (i === 0 ? ini + pmt * n : ini * Math.pow(1 + i, n) + pmt * (Math.pow(1 + i, n) - 1) / i);
const aporteParaMeta = (alvo, ini, n, i) => n <= 0 ? 0 : Math.max(0, (alvo - ini * Math.pow(1 + i, n)) * (i === 0 ? 1 / n : i / (Math.pow(1 + i, n) - 1)));
const rendaAte99 = (P, i, m) => m <= 0 ? 0 : (i === 0 ? P / m : P * i / (1 - Math.pow(1 + i, -m)));
const capitalAte99 = (Y, i, m) => i === 0 ? Y * m : Y * (1 - Math.pow(1 + i, -m)) / i;
const reais = v => Math.round(v);

function calcular(nome, x) {
  x = x || {};
  if (nome === "calcular_aposentadoria") {
    const idade = Number(x.idade_atual), iret = Number(x.idade_renda);
    if (!(idade >= 18 && iret > idade && iret < 99)) return { erro: "Idades inválidas: a renda precisa começar depois da idade atual e antes dos 99 anos." };
    const perfil = PERFIS[x.perfil] ? x.perfil : "moderada";
    const r = PERFIS[perfil], rr = Math.min(4, r);
    const ia = taxaMes(r), ir = taxaMes(rr), n = (iret - idade) * 12, m = (99 - iret) * 12;
    const ini = Number(x.patrimonio_atual) || 0;
    const out = { premissas: `carteira ${perfil}: ${String(r).replace(".", ",")}% ao ano acima da inflação até os ${iret} anos; ${String(rr).replace(".", ",")}% ao ano na fase de renda; valores em reais de hoje; renda até os 99 anos`,
                  anos_ate_renda: iret - idade, patrimonio_atual_projetado: reais(fv(ini, 0, n, ia)) };
    if (x.renda_mensal) {
      const Y = Number(x.renda_mensal);
      const pPres = Y / ir, pCons = capitalAte99(Y, ir, m);
      Object.assign(out, {
        renda_mensal: reais(Y),
        patrimonio_necessario_preservando_capital: reais(pPres),
        patrimonio_necessario_consumindo_ate_99: reais(pCons),
        aporte_mensal_necessario_preservando: reais(aporteParaMeta(pPres, ini, n, ia)),
        aporte_mensal_necessario_consumindo: reais(aporteParaMeta(pCons, ini, n, ia)),
      });
    }
    if (x.aporte_mensal) {
      const P = fv(ini, Number(x.aporte_mensal), n, ia);
      Object.assign(out, {
        aporte_mensal: reais(Number(x.aporte_mensal)),
        patrimonio_projetado: reais(P),
        renda_mensal_preservando_capital: reais(P * ir),
        renda_mensal_consumindo_ate_99: reais(rendaAte99(P, ir, m)),
      });
    }
    return out;
  }
  if (nome === "calcular_meta") {
    const taxa = x.rendimento_real_anual == null ? 4.5 : Number(x.rendimento_real_anual);
    const i = taxaMes(taxa), ini = Number(x.inicial) || 0;
    const meta = x.meta == null ? null : Number(x.meta), pmt = x.aporte_mensal == null ? null : Number(x.aporte_mensal), n = x.meses == null ? null : Math.round(Number(x.meses));
    const base = { premissas: `${String(taxa).replace(".", ",")}% ao ano acima da inflação, juros compostos mensais, valores em reais de hoje`, inicial: reais(ini) };
    if (meta != null && n != null) return { ...base, meta: reais(meta), meses: n, aporte_mensal_necessario: reais(aporteParaMeta(meta, ini, n, i)) };
    if (pmt != null && n != null) {
      const total = fv(ini, pmt, n, i);
      return { ...base, aporte_mensal: reais(pmt), meses: n, valor_acumulado: reais(total), total_guardado: reais(ini + pmt * n), rendimento: reais(total - ini - pmt * n) };
    }
    if (meta != null && pmt != null) {
      if (ini >= meta) return { ...base, meta: reais(meta), meses_necessarios: 0 };
      if (pmt <= 0) return { erro: "Informe um aporte mensal maior que zero." };
      let k = 0, v = ini;
      while (v < meta && k < 1200) { v = v * (1 + i) + pmt; k++; }
      return { ...base, meta: reais(meta), aporte_mensal: reais(pmt), meses_necessarios: k, anos_e_meses: `${Math.floor(k / 12)} anos e ${k % 12} meses` };
    }
    return { erro: "Informe dois entre meta, aporte_mensal e meses." };
  }
  return { erro: "Ferramenta desconhecida." };
}

export default {
  async fetch(request, env, ctx) {
    const origem = request.headers.get("Origin") || "";
    const origens = env.ORIGENS ? env.ORIGENS.split(",").map(s => s.trim()) : ORIGENS_PADRAO;
    const cors = {
      "Access-Control-Allow-Origin": origens.includes(origem) ? origem : origens[0],
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
      "Vary": "Origin",
    };
    const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
      status, headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
    });

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method === "GET") return json({ ok: true, servico: "alfred" });
    if (request.method !== "POST") return json({ erro: "método não permitido" }, 405);
    if (!origens.includes(origem)) return json({ erro: "origem não autorizada" }, 403);
    if (!env.ANTHROPIC_API_KEY) return json({ erro: "O Alfred ainda não foi configurado." }, 500);

    let corpo;
    try { corpo = await request.json(); } catch { return json({ erro: "pedido inválido" }, 400); }

    // Código de acesso da versão de teste
    if (env.ACCESS_CODE && String(corpo.codigo || "").trim().toLowerCase() !== env.ACCESS_CODE.trim().toLowerCase()) {
      return json({ erro: "codigo", mensagem: "Código de acesso inválido." }, 401);
    }

    const mensagens = validar(corpo.mensagens);
    if (!mensagens) return json({ erro: "conversa inválida" }, 400);

    // Limites de uso
    const ip = request.headers.get("CF-Connecting-IP") || "sem-ip";
    const limite = await verificarLimites(env, ip);
    if (limite) return json({ erro: "limite", mensagem: limite }, 429);

    const [instrucoes, dados] = await carregarContexto();
    if (!instrucoes) return json({ erro: "O Alfred está indisponível agora. Tente de novo em alguns minutos." }, 503);

    const sistema = [
      { type: "text", text: instrucoes, cache_control: { type: "ephemeral" } },
      { type: "text", text: dados || "Dados de mercado do painel: indisponíveis no momento. Indique a aba Indicadores." },
    ];

    const modelo = env.MODELO || "claude-sonnet-5-5";
    const conversa = mensagens.slice();
    const blocos = [];
    const uso = { entrada: 0, saida: 0, cache: 0, buscas: 0 };
    let resp = {};
    // Até 5 rodadas: a busca na web pode pausar ("pause_turn") e as calculadoras pedem resposta ("tool_use").
    for (let rodada = 0; rodada < 5; rodada++) {
      let r;
      try {
        r = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "x-api-key": env.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
          },
          body: JSON.stringify({
            model: modelo,
            max_tokens: MAX_TOKENS,
            ...pensamento(modelo),
            system: sistema,
            tools: [BUSCA, ...CALCULADORAS],
            messages: conversa,
          }),
        });
      } catch (e) {
        return json({ erro: "O Alfred não conseguiu responder agora. Tente de novo." }, 502);
      }
      resp = await r.json().catch(() => ({}));
      if (!r.ok) {
        console.error("Anthropic", r.status, JSON.stringify(resp).slice(0, 500));
        const sobrecarga = r.status === 429 || r.status === 529;
        return json({ erro: sobrecarga
          ? "Muita gente conversando com o Alfred agora. Tente de novo em instantes."
          : "O Alfred não conseguiu responder agora. Tente de novo." }, 502);
      }
      const u = resp.usage || {};
      uso.entrada += (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
      uso.saida += u.output_tokens || 0;
      uso.cache += u.cache_read_input_tokens || 0;
      uso.buscas += (u.server_tool_use && u.server_tool_use.web_search_requests) || 0;
      blocos.push(...(resp.content || []));
      if (resp.stop_reason === "pause_turn") { conversa.push({ role: "assistant", content: resp.content }); continue; }
      if (resp.stop_reason !== "tool_use") break;
      const pedidos = (resp.content || []).filter(b => b.type === "tool_use");
      conversa.push({ role: "assistant", content: resp.content });
      conversa.push({ role: "user", content: pedidos.map(b => ({
        type: "tool_result", tool_use_id: b.id, content: JSON.stringify(calcular(b.name, b.input)),
      })) });
    }

    // Descarta o texto escrito antes da última busca ou cálculo ("vou consultar...", "vou calcular...").
    let inicio = 0;
    blocos.forEach((b, i) => { if (["web_search_tool_result", "server_tool_use", "tool_use"].includes(b.type)) inicio = i + 1; });
    let texto = blocos.slice(inicio).filter(b => b.type === "text").map(b => b.text).join("").trim();
    const agendar = /\[AGENDAR\]/.test(texto);
    texto = texto.replace(/\s*\[AGENDAR\]\s*/g, "\n").trim();
    if (!texto) texto = "Não consegui formular uma resposta. Pode reformular a pergunta?";
    if (resp.stop_reason === "max_tokens") texto += "\n\n(Resposta interrompida por tamanho. Peça para eu continuar.)";

    // Registro da conversa na planilha, sem atrasar a resposta
    ctx.waitUntil(registrar({
      sessao: String(corpo.sessao || "").slice(0, 40),
      pergunta: mensagens[mensagens.length - 1].content,
      resposta: texto,
      agendar: agendar ? "sim" : "",
      tokens_entrada: uso.entrada,
      tokens_saida: uso.saida,
      tokens_cache: uso.cache,
      buscas: uso.buscas,
    }));

    return json({ resposta: texto, agendar });
  },
};

/* ---------------------------------------------------------------- modelo */

// Sem "pensamento" prévio: respostas mais rápidas, curtas e baratas.
// Sonnet 5.5 só aceita desligar com "between_tools" (esforço até high); Haiku 5.5 aceita "disabled".
function pensamento(modelo) {
  if (/sonnet-5-5/.test(modelo)) return { thinking: { type: "between_tools" }, output_config: { effort: "medium" } };
  if (/haiku-5-5/.test(modelo)) return { thinking: { type: "disabled" }, output_config: { effort: "medium" } };
  return {};
}

/* ---------------------------------------------------------------- validação */

function validar(lista) {
  if (!Array.isArray(lista) || !lista.length) return null;
  let msgs = lista.slice(-MAX_MENSAGENS).map(m => ({
    role: m && m.role === "assistant" ? "assistant" : "user",
    content: String((m && m.content) || "").slice(0, MAX_CARACTERES).trim(),
  })).filter(m => m.content);
  while (msgs.length && msgs[0].role !== "user") msgs.shift();
  // junta mensagens seguidas do mesmo papel (a API exige alternância)
  const out = [];
  for (const m of msgs) {
    if (out.length && out[out.length - 1].role === m.role) out[out.length - 1].content += "\n\n" + m.content;
    else out.push({ ...m });
  }
  if (!out.length || out[out.length - 1].role !== "user") return null;
  return out;
}

/* ---------------------------------------------------------------- limites */

async function verificarLimites(env, ip) {
  if (!env.LIMITES) return null;   // sem KV ligado, sem limite (só para testes)
  const agora = new Date();
  const dia = agora.toISOString().slice(0, 10);
  const hora = agora.toISOString().slice(0, 13);
  const porIp = Number(env.LIMITE_IP_HORA || 40);
  const porDia = Number(env.LIMITE_DIA || 300);
  const kIp = `ip:${ip}:${hora}`, kDia = `dia:${dia}`;
  const [nIp, nDia] = await Promise.all([env.LIMITES.get(kIp), env.LIMITES.get(kDia)]).then(v => v.map(x => Number(x || 0)));
  if (nIp >= porIp) return "Você atingiu o limite de mensagens por hora. Volte daqui a pouco.";
  if (nDia >= porDia) return "O Alfred atingiu o limite de conversas de hoje. Volte amanhã.";
  await Promise.all([
    env.LIMITES.put(kIp, String(nIp + 1), { expirationTtl: 7200 }),
    env.LIMITES.put(kDia, String(nDia + 1), { expirationTtl: 172800 }),
  ]);
  return null;
}

/* ---------------------------------------------------------------- contexto */

async function carregarContexto() {
  if (memoria.instrucoes && Date.now() - memoria.em < CACHE_SEG * 1000) return [memoria.instrucoes, memoria.dados];
  const [ins, dad] = await Promise.all([
    fetch(`${SITE}/alfred/instrucoes.md`, { cf: { cacheTtl: CACHE_SEG } }).then(r => r.ok ? r.text() : null).catch(() => null),
    fetch(`${SITE}/dados/indicadores.json`, { cf: { cacheTtl: CACHE_SEG } }).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  if (ins) memoria = { instrucoes: ins, dados: dad ? resumirDados(dad) : memoria.dados, em: Date.now() };
  return [memoria.instrucoes, memoria.dados];
}

function resumirDados(d) {
  const I = d.indicadores || {};
  const n = (v, c = 2) => typeof v === "number" ? v.toLocaleString("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c }) : "?";
  const dt = s => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); return m ? `${m[3]}/${m[2]}/${m[1]}` : "?"; };
  const mes = s => { const m = /^(\d{4})-(\d{2})/.exec(s || ""); return m ? `${m[2]}/${m[1]}` : "?"; };
  const L = ["Dados de mercado do painel (coletados de fontes oficiais; cite a data ao usar):"];
  try {
    const s = I.selic;
    if (s && s.atual) {
      let t = `- Selic meta: ${n(s.atual.valor)}% ao ano (${dt(s.atual.data)}).`;
      if (Array.isArray(s.caminho_focus) && s.caminho_focus.length) {
        t += ` Focus de ${dt(s.focus_data)} espera: ` + s.caminho_focus.slice(0, 4).map(([r, v]) => `${r} ${n(v)}%`).join(", ") + ".";
      }
      L.push(t);
    }
    const c = I.ciclo;
    if (c) L.push(`- Ciclo monetário: ${c.estado || "?"}, ${String(c.direcao || "").toLowerCase()}; juro real ex-ante ${n(c.juro_real_exante)}% contra neutro de ${n(c.juro_neutro, 1)}%; Selic esperada em 12 meses ${n(c.selic_12m)}%.`);
    const f = I.inflacao;
    if (f) {
      let t = `- IPCA 12 meses: ${n(f.realizado && f.realizado.valor)}% (até ${mes(f.realizado && f.realizado.data)}); esperado para os próximos 12 meses: ${n(f.esperado_12m && f.esperado_12m.valor)}%; meta ${n(f.meta, 1)}%.`;
      if (f.focus_anos) t += " Focus por ano: " + Object.entries(f.focus_anos).slice(0, 3).map(([a, v]) => `${a} ${n(v)}%`).join(", ") + ".";
      L.push(t);
    }
    const x = I.cambio;
    if (x && x.ptax) L.push(`- Dólar PTAX: R$ ${n(x.ptax.valor, 4)} (${dt(x.ptax.data)}). Câmbio real efetivo (${mes(x.real_efetivo && x.real_efetivo.data)}): ${(x.real_efetivo && x.real_efetivo.leitura) || "?"}, ${n(x.real_efetivo && x.real_efetivo.desvio_pct, 1)}% contra a média de 10 anos.`);
    const e = I.eua;
    if (e) {
      const p = [];
      for (const k of ["vix", "vxewz", "curva", "juro_real_10a"]) if (e[k]) p.push(`${e[k].nome}: ${n(e[k].valor)} (${e[k].leitura}, ${dt(e[k].data)})`);
      if (p.length) L.push("- " + p.join("; ") + ".");
    }
    const b = I.bitcoin;
    if (b && b.preco) L.push(`- Bitcoin: US$ ${n(b.preco.valor, 0)} (${dt(b.preco.data)}); Múltiplo de Mayer ${n(b.mayer && b.mayer.valor)} (${(b.mayer && b.mayer.leitura) || "?"}).`);
  } catch (e) { console.error("resumo", e); }
  L.push(`Atualizado em ${dt(d.gerado_em)}.`);
  return L.join("\n");
}

/* ---------------------------------------------------------------- registro */

async function registrar(campos) {
  try {
    const corpo = new URLSearchParams({ tipo: "alfred", ...Object.fromEntries(Object.entries(campos).map(([k, v]) => [k, String(v)])) });
    await fetch(LEADS_URL, { method: "POST", body: corpo, redirect: "follow" });
  } catch (e) { console.error("registro", e); }
}
