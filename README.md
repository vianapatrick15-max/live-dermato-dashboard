# Dashboard — Live Dermatologia BWS ("Os Caminhos da Dermatologia")

Acompanhamento da captação da Live de Dermatologia (Faculdade BWS), campanha
`dermatologia_live-clinica_0307`. Atualiza sozinho de hora em hora via GitHub Action.

- **Fonte inscritos:** planilha `Grupo Primum | Leads e Pré-Checkout 2026`, aba `[BWS] Live Dermatologia` (formulário HubSpot da LP).
- **Fonte mídia:** API Meta Ads (campanha 120248427297450055).
- **Lead pago:** UTM Campaign contém `art_live_dermato`. **Público certo:** "Você é Médico?" = Sim.

## Como funciona
- `refresh.py` lê a planilha + puxa a campanha no Meta, calcula os indicadores e gera
  `data.json` + `index.html` (auto-contido, gráficos em SVG nativo, sem dependências externas).
- O Action roda `refresh.py` no cron e commita o resultado; o Pages serve o `index.html`.

## Editar metas
As metas (CPL, verba, leads, datas) ficam no topo do `refresh.py` (bloco `METAS`).

## Segredos do repositório (Actions)
- `GOOGLE_SHEETS_CREDENTIALS_JSON` — JSON da service account com acesso à planilha.
- `META_ADS_TOKEN` — token da API Meta com acesso à conta BWS.

## Rodar local
```
pip install -r requirements.txt
python refresh.py   # usa credenciais locais (SA + .env da skill meta-ads-bws)
```
