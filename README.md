# Painel do Investidor

Site de Welton Garcia, CFP®, com:

- **Indicadores**: termômetros de mercado (inflação, Selic, ciclo monetário, câmbio, medo no Brasil e nos EUA, juros americanos e bitcoin), com fonte, data do último dado e frequência de cada um.
- **Investir por objetivos**: reserva de emergência, médio prazo, aposentadoria, educação dos filhos e viagem ao exterior, com notas por critérios técnicos públicos.

## Como funciona

| Arquivo | Função |
|---|---|
| `index.html` | O site inteiro. Lê `dados/indicadores.json` a cada visita. |
| `coletor/coletor_v1.py` | Busca os dados em fontes oficiais e grava `dados/indicadores.json`. Só usa a biblioteca padrão do Python. |
| `.github/workflows/coletar-indicadores.yml` | Roda o coletor automaticamente nos dias úteis às 14h30 e às segundas às 10h30 (horário de Brasília). |

Se uma fonte estiver fora do ar, o coletor mantém o último dado válido daquele indicador, o site avisa no card, e o GitHub manda um e-mail informando a falha.

Para rodar a coleta na hora: aba **Actions** → **Coletar indicadores** → **Run workflow**.

## Fontes

Banco Central do Brasil (SGS e Boletim Focus), IBGE, FRED (Federal Reserve Bank of St. Louis) e alternative.me.

Conteúdo educativo. Não constitui recomendação individual de investimento.

## Formulário de leads

O formulário "Quero agendar minha revisão" envia os dados para uma planilha Google do Welton e manda um aviso por e-mail. O código fica em `apps-script/Code.gs`.

Instalação (uma vez):

1. Criar uma planilha Google em branco.
2. Na planilha: **Extensões → Apps Script**, apagar o conteúdo e colar `apps-script/Code.gs`. Salvar.
3. No editor, escolher a função `autorizar` e clicar em **Executar**; aceitar as permissões.
4. **Implantar → Nova implantação → App da Web**. Executar como: **Eu**. Quem pode acessar: **Qualquer pessoa**. Implantar e copiar a URL.
5. Colocar essa URL em `LEADS_URL` no `index.html`.

Enquanto `LEADS_URL` estiver vazio, o formulário leva o visitante direto ao WhatsApp.

## Insights (estudos)

Os estudos ficam na aba **Estudos** da planilha de leads. Cada linha é um post:

| Coluna | O que preencher |
|---|---|
| Publicar | `Sim` para aparecer no site; qualquer outra coisa esconde |
| Data | data do estudo |
| Título | título do post |
| Resumo | 1 ou 2 frases; aparece na lista e na prévia do WhatsApp/LinkedIn |
| Texto | o conteúdo. Linha em branco separa parágrafos; `## ` cria subtítulo; `- ` cria lista; `**negrito**`; `[texto](https://link)` |
| Link do PDF | link do Google Drive, compartilhado como "qualquer pessoa com o link" (opcional) |
| Imagem | link do Google Drive de uma imagem de capa (opcional) |
| Endereço | preenchido automaticamente na primeira publicação; não altere depois |

O workflow **Publicar insights** roda a cada hora (7h às 23h) e gera uma página por estudo em `insights/<endereço>/`. Para publicar na hora: **Actions → Publicar insights → Run workflow**.

Comentários vão para a aba **Comentarios** e aparecem na hora; para esconder um, mude **Visível** para `Não`. Quem baixa um PDF fica registrado na aba **Downloads**.

## Alfred (assistente de IA, em teste)

- `alfred/index.html`: página do chat (endereço oculto, `noindex`, com código de acesso enquanto `MODO_TESTE = true`).
- `alfred/instrucoes.md`: instruções do Alfred, geradas a partir do Manual do Alfred. Editar este arquivo muda o comportamento em até 10 minutos, sem mexer no Worker.
- `alfred/worker.js`: intermediário no Cloudflare Workers. Guarda a chave da API (segredo `ANTHROPIC_API_KEY`), confere o código de acesso (`ACCESS_CODE`), aplica limites de uso (KV `LIMITES`), junta as instruções e os dados de `dados/indicadores.json` e registra cada pergunta e resposta na aba Alfred da planilha.
- O convite para reunião vem do modelo com a marca `[AGENDAR]`; a página troca a marca pelo formulário, com origem "Alfred".
