#!/usr/bin/env python3
"""
Pipeline do Dashboard — Live Dermatologia BWS ("Os Caminhos da Dermatologia").
Modo TRACKER (sem metas inventadas): so fatos reais.

Emite dados GRANULARES (por dia / anuncio / lead) para que o filtro de datas do
front recalcule tudo no navegador e para que as metricas de anuncio usem o LEAD
QUALIFICADO (medico) em vez do inscrito geral.

Fontes:
  - Inscritos/leads/medico -> planilha "Grupo Primum | Leads e Pre-Checkout 2026"
        aba "[BWS] Live Dermatologia" (formulario HubSpot da LP da live)
  - Spend/impr/clicks/LPV + verba/dia -> API Meta Ads, campanha
        dermatologia_live-clinica_0307 (id 120248427297450055).

Regra de atribuicao:
  Lead PAGO = UTM Campaign contem "art_live_dermato". Resto = organico/outros.
  Lead QUALIFICADO = "Voce e Medico?" comeca com "Sim".
  Metricas de anuncio (vindos de anuncios, custo por inscrito, evolucao) usam o
  lead PAGO + QUALIFICADO (medico vindo de anuncio).
"""
import os, json, urllib.request, datetime as dt
from pathlib import Path
from collections import defaultdict

SID   = "1vcpyCCE0d8zvoSfZqEacvRcJ3yQQgZdogO7CJu32MwA"
TAB   = "[BWS] Live Dermatologia"
CAMP  = "120248427297450055"        # dermatologia_live-clinica_0307
OUT   = Path(__file__).parent / "data.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
LOCAL_CRED = os.path.expanduser("~/.claude/skills/ga4/credentials/ga4-instituto-andhela.json")

# ---------------- DATAS (fatos reais — nao sao metas) ----------------
CAMPAIGN_START = dt.date(2026, 7, 3)   # 1o dia de gasto
EVENT_DATE     = dt.date(2026, 7, 16)  # Live 16/07
# ---------------------------------------------------------------------

try:
    from zoneinfo import ZoneInfo
    TODAY = dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
except Exception:
    TODAY = (dt.datetime.utcnow() - dt.timedelta(hours=3)).date()


# ===================== helpers =====================
def daykey(s):  # "06/07/2026 09:59:44" -> "2026-07-06"
    d = (s or "").strip().split(" ")[0]
    try:
        dd, mm, yy = d.split("/"); return f"{yy}-{mm.zfill(2)}-{dd.zfill(2)}"
    except Exception:
        return ""

def is_paid(c):   return "art_live_dermato" in (c or "").lower()
def is_medico(c): return (c or "").strip().lower().startswith("sim")

def ad_concept(name):
    import re
    m = re.search(r'ad\s*0?(\d)', (name or "").lower())
    return f"ad0{m.group(1)}" if m else None

AD_LABELS = {
    "ad01": "Live Betina e Jorge",
    "ad02": "Estetica ou Clinica",
    "ad03": "Futuro da Dermato Clinica",
    "ad04": "Conversa de Dermatologista",
}


# ===================== Meta Ads (API) =====================
def meta_token():
    tok = os.environ.get("META_ADS_TOKEN")
    if tok:
        return tok
    envp = os.path.expanduser("~/.claude/skills/meta-ads-bws/.env")
    if os.path.exists(envp):
        for line in open(envp):
            line = line.strip()
            if line.startswith("META_ADS_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("META_ADS_TOKEN ausente (env ou .env da skill).")

def gget(url):
    return json.load(urllib.request.urlopen(url, timeout=60))

def gget_all(url):
    out = []
    while url:
        j = gget(url)
        out.extend(j.get("data", []))
        url = j.get("paging", {}).get("next")
    return out

def load_meta():
    """Retorna verba/dia + entrega granular por ANUNCIO x DIA."""
    tok = meta_token()
    base = "https://graph.facebook.com/v21.0"
    daily = 0.0
    try:
        c = gget(f"{base}/{CAMP}?fields=daily_budget&access_token={tok}")
        daily = float(c.get("daily_budget", 0) or 0) / 100.0
    except Exception:
        pass
    u = (f"{base}/{CAMP}/insights?level=ad&time_increment=1"
         f"&fields=ad_name,spend,impressions,clicks,inline_link_clicks,actions"
         f"&date_preset=maximum&limit=500&access_token={tok}")
    deliv = []
    for r in gget_all(u):
        d = r.get("date_start")
        if not d:
            continue
        concept = ad_concept(r.get("ad_name", "")) or (r.get("ad_name", "") or "outros")
        lpv = next((int(a["value"]) for a in r.get("actions", [])
                    if a["action_type"] == "landing_page_view"), 0)
        clk = int(float(r.get("inline_link_clicks", r.get("clicks", 0)) or 0))
        deliv.append({
            "d": d, "ad": concept,
            "s": round(float(r.get("spend", 0) or 0), 2),
            "i": int(float(r.get("impressions", 0) or 0)),
            "c": clk, "lpv": lpv,
        })
    return daily, deliv


# ===================== Sheet =====================
def load_sheet():
    import gspread
    from google.oauth2.service_account import Credentials
    raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH", LOCAL_CRED)
        creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    v = gc.open_by_key(SID).worksheet(TAB).get_all_values()
    h = {c.strip(): i for i, c in enumerate(v[0])}
    def col(r, name):
        i = h.get(name)
        return r[i].strip() if (i is not None and len(r) > i) else ""
    rows = [r for r in v[1:] if any(c.strip() for c in r)
            and col(r, "Data de conversão recente")]
    return rows, col


# ===================== compute =====================
daily_budget, deliv = load_meta()
rows, col = load_sheet()

# um registro por lead (sem PII): dia, pago, medico, conceito do anuncio
leads = []
for r in rows:
    d = daykey(col(r, "Data de conversão recente"))
    if not d:
        continue
    p = 1 if is_paid(col(r, "UTM Campaign")) else 0
    m = 1 if is_medico(col(r, "Você é Médico?")) else 0
    concept = ad_concept(col(r, "UTM Content")) or "outros"
    leads.append({"d": d, "p": p, "m": m, "ad": concept if p else "organico"})

# janela de datas
spend_days = {x["d"] for x in deliv if x["d"]}
lead_days  = {l["d"] for l in leads if l["d"]}
all_days   = spend_days | lead_days
data_from  = min(all_days) if all_days else CAMPAIGN_START.isoformat()
data_to    = max(all_days | {TODAY.isoformat()})

# rotulos dos anuncios presentes
concepts = {x["ad"] for x in deliv} | {l["ad"] for l in leads if l["p"] == 1}
ad_labels = {c: AD_LABELS.get(c, c) for c in concepts if c != "organico"}

data = {
    "updated_at": dt.datetime(TODAY.year, TODAY.month, TODAY.day, 12, 0).isoformat(),
    "today": TODAY.isoformat(),
    "event_date": EVENT_DATE.isoformat(),
    "campaign_start": CAMPAIGN_START.isoformat(),
    "days_left": max(0, (EVENT_DATE - TODAY).days),
    "daily_budget": round(daily_budget, 2),
    "data_from": data_from, "data_to": data_to,
    "ad_labels": ad_labels,
    "deliv": deliv, "leads": leads,
}
OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

base = Path(__file__).parent
tpl = (base / "template.html").read_text()
(base / "index.html").write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False)))

# ===================== resumo =====================
insc = len(leads)
n_paid = sum(l["p"] for l in leads)
qpaid = sum(1 for l in leads if l["p"] == 1 and l["m"] == 1)
medicos = sum(l["m"] for l in leads)
spend = sum(x["s"] for x in deliv)
cpl_q = spend / qpaid if qpaid else 0
print(f"INSCRITOS {insc} (pagos {n_paid} | medicos-pagos {qpaid} | org {insc-n_paid}) | MEDICOS {medicos}")
print(f"SPEND R$ {spend:,.2f} (verba/dia R$ {daily_budget:.0f}) | CUSTO/MEDICO R$ {cpl_q:,.2f}")
# por anuncio (qualificado)
by_ad_s = defaultdict(float); by_ad_q = defaultdict(int)
for x in deliv: by_ad_s[x["ad"]] += x["s"]
for l in leads:
    if l["p"] == 1 and l["m"] == 1: by_ad_q[l["ad"]] += 1
for c in sorted(set(by_ad_s) | set(by_ad_q), key=lambda a: -by_ad_s.get(a, 0)):
    q = by_ad_q.get(c, 0); s = by_ad_s.get(c, 0)
    cpl = f"R$ {s/q:.0f}" if q else "s/ medico"
    print(f"  {ad_labels.get(c, c):<28} R$ {s:>7,.0f} | {q:>2} medicos | {cpl}")
print(f"OK -> {OUT} ({OUT.stat().st_size//1024} KB)")
