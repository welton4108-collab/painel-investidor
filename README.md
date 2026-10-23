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
