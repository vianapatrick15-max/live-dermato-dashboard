#!/usr/bin/env python3
"""
Pipeline do Dashboard — Live Dermatologia BWS ("Os Caminhos da Dermatologia").
Modo TRACKER (sem metas inventadas): so fatos reais.

Fontes:
  - Inscritos/leads/medico -> planilha "Grupo Primum | Leads e Pre-Checkout 2026"
        aba "[BWS] Live Dermatologia" (formulario HubSpot da LP da live)
  - Spend/impr/clicks/LPV + verba/dia -> API Meta Ads, campanha
        dermatologia_live-clinica_0307 (id 120248427297450055).

Regra de atribuicao:
  Lead PAGO = UTM Campaign contem "art_live_dermato". Resto = organico/outros.
  Publico certo = "Voce e Medico?" comeca com "Sim".
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
        dd, mm, yy = d.split("/"); return f"{yy}-{mm}-{dd}"
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

def load_meta():
    tok = meta_token()
    base = "https://graph.facebook.com/v21.0"
    # verba/dia real (campanha CBO)
    daily = 0.0
    try:
        c = gget(f"{base}/{CAMP}?fields=daily_budget&access_token={tok}")
        daily = float(c.get("daily_budget", 0) or 0) / 100.0
    except Exception:
        pass
    # diario (campanha)
    u = (f"{base}/{CAMP}/insights?level=campaign&time_increment=1"
         f"&fields=spend,impressions,clicks,inline_link_clicks,actions"
         f"&date_preset=maximum&access_token={tok}")
    spend_by_day = defaultdict(float); lpv_by_day = defaultdict(int)
    spend = impr = clk = lpv = 0.0
    for r in gget(u).get("data", []):
        d = r["date_start"]; sp = float(r.get("spend", 0) or 0)
        spend += sp; spend_by_day[d] += sp
        impr += float(r.get("impressions", 0) or 0)
        clk  += float(r.get("inline_link_clicks", r.get("clicks", 0)) or 0)
        lv = next((int(a["value"]) for a in r.get("actions", [])
                   if a["action_type"] == "landing_page_view"), 0)
        lpv += lv; lpv_by_day[d] += lv
    # por anuncio -> conceito ad0X
    u2 = (f"{base}/{CAMP}/insights?level=ad"
          f"&fields=ad_name,spend,actions&date_preset=maximum&limit=200&access_token={tok}")
    spend_by_ad = defaultdict(float); lpv_by_ad = defaultdict(int)
    for r in gget(u2).get("data", []):
        c = ad_concept(r.get("ad_name", "")) or r.get("ad_name", "")
        spend_by_ad[c] += float(r.get("spend", 0) or 0)
        lpv_by_ad[c] += next((int(a["value"]) for a in r.get("actions", [])
                              if a["action_type"] == "landing_page_view"), 0)
    return dict(spend=spend, impr=impr, clk=clk, lpv=lpv, daily_budget=daily,
                spend_by_day=spend_by_day, lpv_by_day=lpv_by_day,
                spend_by_ad=spend_by_ad, lpv_by_ad=lpv_by_ad)


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
meta = load_meta()
rows, col = load_sheet()

total_inscritos = len(rows)
paid = [r for r in rows if is_paid(col(r, "UTM Campaign"))]
organico = [r for r in rows if r not in paid]
medicos = sum(1 for r in rows if is_medico(col(r, "Você é Médico?")))
n_paid, n_org = len(paid), len(organico)

leads_by_day = defaultdict(int); paid_by_day = defaultdict(int); leads_by_ad = defaultdict(int)
for r in rows:
    leads_by_day[daykey(col(r, "Data de conversão recente"))] += 1
for r in paid:
    paid_by_day[daykey(col(r, "Data de conversão recente"))] += 1
    leads_by_ad[ad_concept(col(r, "UTM Content")) or "outros"] += 1

spend = meta["spend"]; impr = meta["impr"]; clk = meta["clk"]; lpv = meta["lpv"]
cpl_real = spend / n_paid if n_paid else 0

# ritmo / projecao NEUTRA (run-rate, sem meta)
all_days = sorted(d for d in (set(meta["spend_by_day"]) | set(leads_by_day)) if d)
full_days = [d for d in all_days if d < TODAY.isoformat()]
n_full = max(len(full_days), 1)
days_left = max(0, (EVENT_DATE - TODAY).days)
paid_per_day  = sum(paid_by_day[d]  for d in full_days) / n_full
total_per_day = sum(leads_by_day[d] for d in full_days) / n_full
spend_per_day = sum(meta["spend_by_day"][d] for d in full_days) / n_full
proj_paid  = round(n_paid + paid_per_day * (days_left + 1))
proj_total = round(total_inscritos + total_per_day * (days_left + 1))
proj_spend = round(spend + spend_per_day * (days_left + 1), 2)

# series acumuladas
series = []
cum_paid = cum_total = cum_spend = 0
for d in all_days:
    cum_paid  += paid_by_day.get(d, 0)
    cum_total += leads_by_day.get(d, 0)
    cum_spend += meta["spend_by_day"].get(d, 0)
    series.append({"day": d, "leads_paid": paid_by_day.get(d, 0),
                   "leads_total": leads_by_day.get(d, 0),
                   "spend": round(meta["spend_by_day"].get(d, 0), 2),
                   "cum_paid": cum_paid, "cum_total": cum_total,
                   "cum_spend": round(cum_spend, 2)})

# por criativo
ads = []
for c in sorted(set(meta["spend_by_ad"]) | set(leads_by_ad),
                key=lambda a: -meta["spend_by_ad"].get(a, 0)):
    sp = round(meta["spend_by_ad"].get(c, 0), 2); ld = leads_by_ad.get(c, 0)
    ads.append({"ad": c, "label": AD_LABELS.get(c, c), "spend": sp, "leads": ld,
                "lpv": int(meta["lpv_by_ad"].get(c, 0)),
                "cpl": round(sp / ld, 2) if ld else None})

data = {
    "updated_at": dt.datetime(TODAY.year, TODAY.month, TODAY.day).isoformat(),
    "today": TODAY.isoformat(),
    "event_date": EVENT_DATE.isoformat(),
    "campaign_start": CAMPAIGN_START.isoformat(),
    "days_left": days_left,
    "daily_budget": round(meta["daily_budget"], 2),
    "kpis": {
        "inscritos": total_inscritos, "leads_pagos": n_paid, "organico": n_org,
        "medicos": medicos,
        "pct_medico": round(100 * medicos / total_inscritos, 1) if total_inscritos else 0,
        "spend": round(spend, 2), "impressions": int(impr), "clicks": int(clk), "lpv": int(lpv),
        "cpl_real": round(cpl_real, 2),
        "cpc": round(spend / clk, 2) if clk else 0,
        "conv_lpv_lead": round(100 * n_paid / lpv, 1) if lpv else 0,
    },
    "pace": {
        "full_days": n_full,
        "paid_per_day": round(paid_per_day, 1),
        "total_per_day": round(total_per_day, 1),
        "spend_per_day": round(spend_per_day, 2),
        "proj_paid": proj_paid, "proj_total": proj_total, "proj_spend": proj_spend,
    },
    "series": series, "ads": ads,
}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))

base = Path(__file__).parent
tpl = (base / "template.html").read_text()
(base / "index.html").write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False)))

print(f"INSCRITOS {total_inscritos} (pagos {n_paid} | org {n_org}) | MEDICOS {medicos} ({data['kpis']['pct_medico']}%)")
print(f"SPEND R$ {spend:,.2f} (verba/dia R$ {meta['daily_budget']:.0f}) | CPL R$ {cpl_real:,.2f} | LPV {int(lpv)} conv {data['kpis']['conv_lpv_lead']}%")
print(f"ritmo {paid_per_day:.1f} pagos/dia | proj run-rate {proj_paid} pagos ate {EVENT_DATE} ({days_left}d)")
for a in ads:
    cpl = f"R$ {a['cpl']:.0f}" if a['cpl'] else "s/ lead"
    print(f"  {a['label']:<28} R$ {a['spend']:>7,.0f} | {a['leads']:>2} leads | {cpl}")
print(f"OK -> {OUT}")
