/**
 * Backend do site painel.objetivoprimeiro.com, ligado a esta planilha.
 *
 * Abas usadas (criadas automaticamente por criarAbas):
 *   Leads        pedidos de reunião
 *   Estudos      posts da aba Insights (você preenche)
 *   Comentarios  comentários dos visitantes nos estudos
 *   Downloads    quem baixou o PDF de um estudo
 *   Alfred       perguntas e respostas do assistente Alfred
 *
 * Depois de alterar este código: Implantar > Gerenciar implantações >
 * lápis > Versão: Nova versão > Implantar. O endereço continua o mesmo.
 */

const EMAIL_AVISO = "welton.4108@gmail.com";

const ABA_LEADS = "Leads";
const COL_LEADS = ["Data e hora", "Nome", "WhatsApp", "E-mail", "Objetivo", "Patrimônio",
                   "Página de origem", "Consentimento LGPD", "Status"];
const ABA_ESTUDOS = "Estudos";
const COL_ESTUDOS = ["Publicar", "Data", "Título", "Resumo", "Texto", "Link do PDF", "Imagem", "Endereço"];
const ABA_COMENT = "Comentarios";
const COL_COMENT = ["Data e hora", "Estudo", "Nome", "Comentário", "Visível"];
const ABA_DOWN = "Downloads";
const COL_DOWN = ["Data e hora", "Estudo", "Nome", "E-mail", "Consentimento LGPD"];
const ABA_ALFRED = "Alfred";
const COL_ALFRED = ["Data e hora", "Conversa", "Pergunta", "Resposta", "Convidou para reunião",
                    "Tokens de entrada", "Tokens de saída", "Tokens do cache"];

/* ------------------------------------------------------------ entrada */

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.action === "posts") return resposta({ ok: true, posts: listarEstudos() });
  if (p.action === "comentarios") return resposta({ ok: true, comentarios: listarComentarios(p.post) });
  return resposta({ ok: true, servico: "leads painel" });
}

function doPost(e) {
  const p = (e && e.parameter) || {};
  const tipo = p.tipo || "lead";
  // Campo invisível anti-robô. O preenchimento automático de alguns celulares Android
  // também preenche esse campo, então pedidos de reunião não são descartados:
  // são gravados e marcados para conferência.
  if (p.site_url && tipo !== "lead") return resposta({ ok: true });
  if (tipo === "comentario") return salvarComentario(p);
  if (tipo === "pdf") return salvarDownload(p);
  if (tipo === "alfred") return salvarAlfred(p);
  return salvarLead(p);
}

/* ------------------------------------------------------------ leads */

function salvarLead(p) {
  const nome = limpar(p.nome, 120);
  const zap = String(p.whatsapp || "").replace(/\D/g, "").slice(0, 15);
  if (!nome || zap.length < 10 || p.consentimento !== "sim") {
    return resposta({ ok: false, erro: "dados incompletos" });
  }
  const agora = agoraBR();
  const suspeito = String(p.site_url || "").trim();
  const status = suspeito ? "Conferir (campo anti-robô veio preenchido: " + limpar(suspeito, 60) + ")" : "Novo";
  gravar(ABA_LEADS, COL_LEADS, [
    agora, seguro(nome), seguro(formatarZap(zap)), seguro(limpar(p.email, 120)),
    seguro(limpar(p.objetivo, 60)), seguro(limpar(p.patrimonio, 60)), seguro(limpar(p.origem, 80)),
    "Sim, " + agora, seguro(status)
  ]);
  avisar((suspeito ? "[conferir] " : "") + "Novo pedido de reunião: " + nome, [
    "Novo pedido de reunião pelo painel.", "",
    "Nome: " + nome,
    "WhatsApp: " + formatarZap(zap) + "  (https://wa.me/55" + zap.replace(/^55/, "") + ")",
    "E-mail: " + (limpar(p.email, 120) || "não informado"),
    "Objetivo: " + limpar(p.objetivo, 60),
    "Patrimônio: " + limpar(p.patrimonio, 60),
    "Página de origem: " + limpar(p.origem, 80),
    suspeito ? "\nAtenção: o campo anti-robô veio preenchido (" + limpar(suspeito, 60) + "). Pode ser preenchimento automático do celular; confira antes de chamar." : ""
  ]);
  return resposta({ ok: true });
}

/* ------------------------------------------------------------ estudos */

function listarEstudos() {
  const aba = obterAba(ABA_ESTUDOS, COL_ESTUDOS);
  const dados = aba.getDataRange().getValues();
  if (dados.length < 2) return [];
  const cab = dados[0].map(String);
  const c = nome => cab.indexOf(nome);
  const usados = {};
  const out = [];
  for (let i = 1; i < dados.length; i++) {
    const row = dados[i];
    const titulo = String(row[c("Título")] || "").trim();
    if (!titulo) continue;
    let slug = String(row[c("Endereço")] || "").trim();
    if (!slug) {
      slug = gerarSlug(titulo, usados);
      aba.getRange(i + 1, c("Endereço") + 1).setValue(slug);
    }
    usados[slug] = true;
    if (String(row[c("Publicar")] || "").trim().toLowerCase() !== "sim") continue;
    const d = row[c("Data")];
    out.push({
      slug: slug,
      titulo: titulo,
      data: d instanceof Date ? Utilities.formatDate(d, "America/Sao_Paulo", "yyyy-MM-dd") : String(d || ""),
      resumo: String(row[c("Resumo")] || "").trim(),
      texto: String(row[c("Texto")] || ""),
      pdf: linkDrive(String(row[c("Link do PDF")] || "").trim(), "download"),
      imagem: linkDrive(String(row[c("Imagem")] || "").trim(), "imagem")
    });
  }
  out.sort((a, b) => (b.data > a.data ? 1 : b.data < a.data ? -1 : 0));
  return out;
}

function gerarSlug(titulo, usados) {
  let base = titulo.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "estudo";
  let s = base, n = 2;
  while (usados[s]) s = base + "-" + (n++);
  return s;
}

function linkDrive(link, modo) {
  if (!link) return "";
  const m = link.match(/\/d\/([\w-]{10,})/) || link.match(/[?&]id=([\w-]{10,})/);
  if (!m) return link;
  return modo === "download"
    ? "https://drive.google.com/uc?export=download&id=" + m[1]
    : "https://drive.google.com/thumbnail?id=" + m[1] + "&sz=w1200";
}

/* ------------------------------------------------------------ comentários */

function listarComentarios(post) {
  const slug = limpar(post, 80);
  if (!slug) return [];
  const aba = obterAba(ABA_COMENT, COL_COMENT);
  const dados = aba.getDataRange().getValues();
  const out = [];
  for (let i = 1; i < dados.length; i++) {
    const r = dados[i];
    if (String(r[1]) !== slug) continue;
    if (String(r[4] || "").trim().toLowerCase() === "não" || String(r[4] || "").trim().toLowerCase() === "nao") continue;
    out.push({ data: String(r[0]), nome: String(r[2]), texto: String(r[3]) });
  }
  return out.slice(-200);
}

function salvarComentario(p) {
  const slug = limpar(p.post, 80);
  const nome = limpar(p.nome, 60);
  const texto = String(p.comentario || "").replace(/\r/g, "").trim().slice(0, 1000);
  if (!slug || !nome || texto.length < 2) return resposta({ ok: false, erro: "dados incompletos" });
  gravar(ABA_COMENT, COL_COMENT, [agoraBR(), slug, seguro(nome), seguro(texto), "Sim"]);
  avisar("Novo comentário em " + slug + ": " + nome, [
    "Novo comentário publicado no estudo " + slug + ".", "",
    "Nome: " + nome, "", texto, "",
    "Para esconder, mude a coluna Visível para Não na aba Comentarios."
  ]);
  return resposta({ ok: true });
}

/* ------------------------------------------------------------ downloads */

function salvarDownload(p) {
  const slug = limpar(p.post, 80);
  const nome = limpar(p.nome, 120);
  const email = limpar(p.email, 120);
  if (!slug || !nome || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || p.consentimento !== "sim") {
    return resposta({ ok: false, erro: "dados incompletos" });
  }
  const agora = agoraBR();
  gravar(ABA_DOWN, COL_DOWN, [agora, slug, seguro(nome), seguro(email), "Sim, " + agora]);
  avisar("Novo download: " + nome + " (" + slug + ")", [
    "Alguém baixou o PDF do estudo " + slug + ".", "",
    "Nome: " + nome, "E-mail: " + email
  ]);
  return resposta({ ok: true });
}

/* ------------------------------------------------------------ alfred */

// Registro das conversas, enviado pelo intermediário do Alfred (sem e-mail de aviso).
function salvarAlfred(p) {
  const texto = (v, max) => String(v || "").replace(/\r/g, "").trim().slice(0, max);
  const num = v => Number(String(v || "0").replace(/\D/g, "")) || 0;
  const pergunta = texto(p.pergunta, 2000);
  if (!pergunta) return resposta({ ok: false });
  gravar(ABA_ALFRED, COL_ALFRED, [
    agoraBR(), seguro(limpar(p.sessao, 40)), seguro(pergunta), seguro(texto(p.resposta, 5000)),
    p.agendar === "sim" ? "Sim" : "", num(p.tokens_entrada), num(p.tokens_saida), num(p.tokens_cache)
  ]);
  return resposta({ ok: true });
}

/* ------------------------------------------------------------ utilidades */

function gravar(nomeAba, colunas, linha) {
  const trava = LockService.getScriptLock();
  trava.waitLock(10000);
  try { obterAba(nomeAba, colunas).appendRow(linha); }
  finally { trava.releaseLock(); }
}

function avisar(assunto, linhas) {
  try {
    MailApp.sendEmail({
      to: EMAIL_AVISO, subject: assunto,
      body: linhas.concat(["", "Planilha: " + SpreadsheetApp.getActiveSpreadsheet().getUrl()]).join("\n")
    });
  } catch (err) { console.error(err); }   // o registro já foi gravado
}

function obterAba(nome, colunas) {
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
  let aba = planilha.getSheetByName(nome);
  if (!aba) aba = planilha.insertSheet(nome);
  if (aba.getLastRow() === 0) {
    aba.appendRow(colunas);
    aba.setFrozenRows(1);
    aba.getRange(1, 1, 1, colunas.length).setFontWeight("bold");
  }
  return aba;
}

function agoraBR() { return Utilities.formatDate(new Date(), "America/Sao_Paulo", "dd/MM/yyyy HH:mm"); }
function limpar(v, max) { return String(v || "").replace(/[\r\n\t]+/g, " ").trim().slice(0, max); }
function seguro(v) { return /^[=+\-@]/.test(v) ? "'" + v : v; }   // evita virar fórmula

function formatarZap(d) {
  const n = d.replace(/^55(?=\d{10,11}$)/, "");
  if (n.length === 11) return "(" + n.slice(0, 2) + ") " + n.slice(2, 7) + "-" + n.slice(7);
  if (n.length === 10) return "(" + n.slice(0, 2) + ") " + n.slice(2, 6) + "-" + n.slice(6);
  return d;
}

function resposta(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/** Rode uma vez pelo editor: cria as abas e um estudo de exemplo (não publicado). */
function criarAbas() {
  obterAba(ABA_LEADS, COL_LEADS);
  obterAba(ABA_COMENT, COL_COMENT);
  obterAba(ABA_DOWN, COL_DOWN);
  obterAba(ABA_ALFRED, COL_ALFRED);
  const est = obterAba(ABA_ESTUDOS, COL_ESTUDOS);
  if (est.getLastRow() === 1) {
    est.appendRow(["Não", new Date(), "Exemplo: como ler o Boletim Focus",
      "Um guia rápido para entender o que o mercado espera para juros e inflação.",
      "O Boletim Focus reúne as projeções de cerca de 100 instituições.\n\n## O que olhar primeiro\n\n- A Selic esperada para o fim do ano\n- O IPCA esperado para os próximos 12 meses\n\nUse **negrito** com dois asteriscos e links assim: [Banco Central](https://www.bcb.gov.br).",
      "", "", ""]);
    est.setColumnWidth(5, 420);
  }
  MailApp.getRemainingDailyQuota();
}

/** Mantido por compatibilidade. */
function autorizar() { criarAbas(); }
