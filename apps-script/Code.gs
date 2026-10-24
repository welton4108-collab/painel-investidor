/**
 * Recebe os pedidos de reunião do site painel.objetivoprimeiro.com,
 * grava na aba "Leads" desta planilha e envia um aviso por e-mail.
 *
 * Como instalar: veja o README do repositório (seção "Formulário de leads").
 */

const EMAIL_AVISO = "welton.4108@gmail.com";
const ABA = "Leads";
const COLUNAS = ["Data e hora", "Nome", "WhatsApp", "E-mail", "Objetivo", "Patrimônio",
                 "Página de origem", "Consentimento LGPD", "Status"];

function doPost(e) {
  const p = (e && e.parameter) || {};

  // Campo invisível: só robôs preenchem. Descarta sem gravar.
  if (p.site_url) return resposta({ ok: true });

  const nome = limpar(p.nome, 120);
  const zap = String(p.whatsapp || "").replace(/\D/g, "").slice(0, 15);
  if (!nome || zap.length < 10 || p.consentimento !== "sim") {
    return resposta({ ok: false, erro: "dados incompletos" });
  }

  const trava = LockService.getScriptLock();
  trava.waitLock(10000);
  try {
    const aba = obterAba();
    const agora = Utilities.formatDate(new Date(), "America/Sao_Paulo", "dd/MM/yyyy HH:mm");
    aba.appendRow([
      agora,
      seguro(nome),
      seguro(formatarZap(zap)),
      seguro(limpar(p.email, 120)),
      seguro(limpar(p.objetivo, 60)),
      seguro(limpar(p.patrimonio, 60)),
      seguro(limpar(p.origem, 60)),
      "Sim, " + agora,
      "Novo"
    ]);
  } finally {
    trava.releaseLock();
  }

  try {
    MailApp.sendEmail({
      to: EMAIL_AVISO,
      subject: "Novo pedido de reunião: " + nome,
      body: [
        "Novo pedido de reunião pelo painel.",
        "",
        "Nome: " + nome,
        "WhatsApp: " + formatarZap(zap) + "  (https://wa.me/55" + zap.replace(/^55/, "") + ")",
        "E-mail: " + (limpar(p.email, 120) || "não informado"),
        "Objetivo: " + limpar(p.objetivo, 60),
        "Patrimônio: " + limpar(p.patrimonio, 60),
        "Página de origem: " + limpar(p.origem, 60),
        "",
        "Planilha: " + SpreadsheetApp.getActiveSpreadsheet().getUrl()
      ].join("\n")
    });
  } catch (err) {
    // O lead já está gravado; uma falha no e-mail não deve perdê-lo.
    console.error(err);
  }

  return resposta({ ok: true });
}

function doGet() {
  return resposta({ ok: true, servico: "leads painel" });
}

function obterAba() {
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
  let aba = planilha.getSheetByName(ABA);
  if (!aba) {
    aba = planilha.insertSheet(ABA);
  }
  if (aba.getLastRow() === 0) {
    aba.appendRow(COLUNAS);
    aba.setFrozenRows(1);
    aba.getRange(1, 1, 1, COLUNAS.length).setFontWeight("bold");
  }
  return aba;
}

function limpar(v, max) {
  return String(v || "").replace(/[\r\n\t]+/g, " ").trim().slice(0, max);
}

// Impede que um texto começando com = + - @ vire fórmula na planilha.
function seguro(v) {
  return /^[=+\-@]/.test(v) ? "'" + v : v;
}

function formatarZap(d) {
  const n = d.replace(/^55(?=\d{10,11}$)/, "");
  if (n.length === 11) return "(" + n.slice(0, 2) + ") " + n.slice(2, 7) + "-" + n.slice(7);
  if (n.length === 10) return "(" + n.slice(0, 2) + ") " + n.slice(2, 6) + "-" + n.slice(6);
  return d;
}

function resposta(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Rode esta função uma vez pelo editor para autorizar o acesso à planilha e ao e-mail. */
function autorizar() {
  obterAba();
  MailApp.getRemainingDailyQuota();
}
