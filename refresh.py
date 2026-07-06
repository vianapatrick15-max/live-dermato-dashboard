#!/usr/bin/env python3
"""
Pipeline do Dashboard — Live Dermatologia BWS ("Os Caminhos da Dermatologia").

Fontes:
  - Inscritos/leads/medico -> planilha "Grupo Primum | Leads e Pre-Checkout 2026"
        aba "[BWS] Live Dermatologia" (formulario HubSpot da LP da live)
  - Spend/impr/clicks/LPV    -> API Meta Ads, campanha dermatologia_live-clinica_0307
        (id 120248427297450055) — a planilha nao tem aba de gerenciador.

Regra de atribuicao:
  Lead PAGO   = UTM Campaign contem "art_live_dermato".
  Lead organico/outros = o resto.
  Publico certo = "Voce e Medico?" comeca com "Sim".

Gera data.json + index.html (auto-contido, graficos em SVG nativo).
"""
import os, json, urllib.request, urllib.parse, datetime as dt
from pathlib import Path
from collections import defaultdict

SID   = "1vcpyCCE0d8zvoSfZqEacvRcJ3yQQgZdogO7CJu32MwA"
TAB   = "[BWS] Live Dermatologia"
CAMP  = "120248427297450055"        # dermatologia_live-clinica_0307
OUT   = Path(__file__).parent / "data.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
LOCAL_CRED = os.path.expanduser("~/.claude/skills/ga4/credentials/ga4-instituto-andhela.json")

# ---------------- METAS (provisorias — editar aqui) ----------------
CPL_TARGET         = 60.0
BUDGET             = 7000.0
LEADS_PAGOS_TARGET = 120
ORGANICO_TARGET    = 30
TOTAL_TARGET       = 150
CAMPAIGN_START     = dt.date(2026, 7, 3)
EVENT_DATE         = dt.date(2026, 7, 16)   # Live 16/07
# -------------------------------------------------------------------

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

def is_paid(c):    return "art_live_dermato" in (c or "").lower()
def is_medico(c):  return (c or "").strip().lower().startswith("sim")

def ad_concept(name):
    """Normaliza UTM Content / Ad Name para um conceito ad01-ad04 (nomes de UTM
    congelaram no nome antigo com colchetes; os ads novos usam ad0X_...)."""
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
    # diario (campanha)
    u = (f"{base}/{CAMP}/insights?level=campaign&time_increment=1"
         f"&fields=spend,impressions,clicks,inline_link_clicks,actions"
         f"&date_preset=maximum&access_token={tok}")
    spend_by_day = defaultdict(float); lpv_by_day = defaultdict(int)
    spend = impr = clk = lpv = 0.0
    for r in gget(u).get("data", []):
        d = r["date_start"]
        sp = float(r.get("spend", 0) or 0)
        spend += sp; spend_by_day[d] += sp
        impr += float(r.get("impressions", 0) or 0)
        clk  += float(r.get("inline_link_clicks", r.get("clicks", 0)) or 0)
        lv = next((int(a["value"]) for a in r.get("actions", [])
                   if a["action_type"] == "landing_page_view"), 0)
        lpv += lv; lpv_by_day[d] += lv
    # por anuncio (totais) -> agrega por conceito ad0X
    u2 = (f"{base}/{CAMP}/insights?level=ad"
          f"&fields=ad_name,spend,actions&date_preset=maximum&limit=200&access_token={tok}")
    spend_by_ad = defaultdict(float); lpv_by_ad = defaultdict(int)
    for r in gget(u2).get("data", []):
        c = ad_concept(r.get("ad_name", "")) or r.get("ad_name", "")
        spend_by_ad[c] += float(r.get("spend", 0) or 0)
        lpv_by_ad[c] += next((int(a["value"]) for a in r.get("actions", [])
                              if a["action_type"] == "landing_page_view"), 0)
    return dict(spend=spend, impr=impr, clk=clk, lpv=lpv,
                spend_by_day=spend_by_day, lpv_by_day=lpv_by_day,
                spend_by_ad=spend_by_ad, lpv_by_ad=lpv_by_ad)


# ===================== Sheet (inscritos) =====================
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
    ws = gc.open_by_key(SID).worksheet(TAB)
    v = ws.get_all_values()
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

leads_by_day = defaultdict(int); paid_by_day = defaultdict(int)
leads_by_ad  = defaultdict(int)
for r in rows:
    leads_by_day[daykey(col(r, "Data de conversão recente"))] += 1
for r in paid:
    paid_by_day[daykey(col(r, "Data de conversão recente"))] += 1
    c = ad_concept(col(r, "UTM Content")) or "outros"
    leads_by_ad[c] += 1

spend = meta["spend"]; impr = meta["impr"]; clk = meta["clk"]; lpv = meta["lpv"]
cpl_real = spend / n_paid if n_paid else 0

# ---------- pace / projecao ----------
all_days = sorted(d for d in (set(meta["spend_by_day"]) | set(leads_by_day)) if d)
full_days = [d for d in all_days if d < TODAY.isoformat()]
n_full = max(len(full_days), 1)
days_left = max(0, (EVENT_DATE - TODAY).days)

paid_per_day_full  = sum(paid_by_day[d]  for d in full_days) / n_full
total_per_day_full = sum(leads_by_day[d] for d in full_days) / n_full
spend_per_day_full = sum(meta["spend_by_day"][d] for d in full_days) / n_full

proj_paid  = round(n_paid + paid_per_day_full * (days_left + 1))
proj_total = round(total_inscritos + total_per_day_full * (days_left + 1))
proj_spend = round(spend + spend_per_day_full * (days_left + 1), 2)
need_paid_per_day = (LEADS_PAGOS_TARGET - n_paid) / (days_left + 1) if days_left >= 0 else 0
budget_left = BUDGET - spend
budget_per_day_needed = budget_left / (days_left + 1) if days_left >= 0 else 0

# ---------- series acumuladas ----------
series_days = sorted(d for d in (set(meta["spend_by_day"]) | set(leads_by_day)) if d)
cum_paid = cum_total = cum_spend = 0
series = []
for d in series_days:
    cum_paid  += paid_by_day.get(d, 0)
    cum_total += leads_by_day.get(d, 0)
    cum_spend += meta["spend_by_day"].get(d, 0)
    series.append({
        "day": d,
        "leads_paid": paid_by_day.get(d, 0),
        "leads_total": leads_by_day.get(d, 0),
        "spend": round(meta["spend_by_day"].get(d, 0), 2),
        "cum_paid": cum_paid, "cum_total": cum_total,
        "cum_spend": round(cum_spend, 2),
    })

# ---------- por criativo ----------
ads = []
for c in sorted(set(meta["spend_by_ad"]) | set(leads_by_ad),
                key=lambda a: -meta["spend_by_ad"].get(a, 0)):
    sp = round(meta["spend_by_ad"].get(c, 0), 2)
    ld = leads_by_ad.get(c, 0)
    ads.append({
        "ad": c, "label": AD_LABELS.get(c, c),
        "spend": sp, "leads": ld,
        "lpv": int(meta["lpv_by_ad"].get(c, 0)),
        "cpl": round(sp / ld, 2) if ld else None,
    })

data = {
    "updated_at": dt.datetime.now().replace(microsecond=0).isoformat()
                  if False else dt.datetime(TODAY.year, TODAY.month, TODAY.day).isoformat(),
    "today": TODAY.isoformat(),
    "event_date": EVENT_DATE.isoformat(),
    "campaign_start": CAMPAIGN_START.isoformat(),
    "days_left": days_left,
    "targets": {"cpl": CPL_TARGET, "budget": BUDGET,
                "leads_pagos": LEADS_PAGOS_TARGET, "organico": ORGANICO_TARGET, "total": TOTAL_TARGET},
    "kpis": {
        "inscritos": total_inscritos, "leads_pagos": n_paid, "organico": n_org,
        "medicos": medicos,
        "pct_medico": round(100 * medicos / total_inscritos, 1) if total_inscritos else 0,
        "spend": round(spend, 2), "impressions": int(impr), "clicks": int(clk), "lpv": int(lpv),
        "cpl_real": round(cpl_real, 2),
        "cpc": round(spend / clk, 2) if clk else 0,
        "conv_lpv_lead": round(100 * n_paid / lpv, 1) if lpv else 0,
        "pct_budget_gasto": round(100 * spend / BUDGET, 1) if BUDGET else 0,
    },
    "pace": {
        "full_days": n_full,
        "paid_per_day": round(paid_per_day_full, 1),
        "total_per_day": round(total_per_day_full, 1),
        "spend_per_day": round(spend_per_day_full, 2),
        "need_paid_per_day": round(need_paid_per_day, 1),
        "budget_per_day_needed": round(budget_per_day_needed, 2),
        "proj_paid": proj_paid, "proj_total": proj_total, "proj_spend": proj_spend,
        "on_track_leads": proj_paid >= LEADS_PAGOS_TARGET,
        "on_track_cpl": cpl_real <= CPL_TARGET,
    },
    "series": series, "ads": ads,
}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))

# render
base = Path(__file__).parent
tpl = (base / "template.html").read_text()
(base / "index.html").write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False)))

# resumo terminal
print(f"INSCRITOS {total_inscritos} (meta {TOTAL_TARGET}) | PAGOS {n_paid} (meta {LEADS_PAGOS_TARGET}) | ORG {n_org}")
print(f"MEDICOS {medicos}/{total_inscritos} ({data['kpis']['pct_medico']}%)")
print(f"SPEND R$ {spend:,.2f}/{BUDGET:,.0f} ({data['kpis']['pct_budget_gasto']}%) | CPL R$ {cpl_real:,.2f} (meta {CPL_TARGET:.0f})")
print(f"LPV {int(lpv)} | conv LPV->pago {data['kpis']['conv_lpv_lead']}% | dias ate live {days_left}")
print(f"PROJ run-rate: {proj_paid} pagos | {proj_total} inscritos | R$ {proj_spend:,.0f}")
for a in ads:
    cpl = f"R$ {a['cpl']:.0f}" if a['cpl'] else "s/ lead"
    print(f"  {a['label']:<28} R$ {a['spend']:>7,.0f} | {a['leads']:>2} leads | {cpl}")
print(f"OK -> {OUT}")
