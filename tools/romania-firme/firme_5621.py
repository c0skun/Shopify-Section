#!/usr/bin/env python3
"""
Romanya'daki CAEN 5621 (catering pentru evenimente) firmalarini resmi acik
veriden toplayip il il ayri sayfalara, ciroya gore sirali bir Excel'e yazar.

Kaynaklar:
  1. data.gov.ro  - ONRC firma listesi (od_firme, od_caen_autorizat, od_stare_firma)
                    -> CAEN 5621 icin yetkili tum firmalar = aday liste
  2. ANAF bilant  - webservicesp.anaf.ro/bilant  -> CAEN preponderent, ciro, kar,
                    calisan sayisi (bilancodaki ana faaliyet kodu)
  3. ANAF TVA API - webservicesp.anaf.ro/api/PlatitorTvaRest -> adres, telefon, durum

Kullanim:
  pip install -r requirements.txt
  python firme_5621.py                   # hepsini indirir ve calistirir
  python firme_5621.py --onrc-dir ./onrc # ONRC dosyalarini elle indirdiyseniz

Script yarida kesilirse ayni komutla tekrar calistirin; ANAF cevaplari
cache/ klasorunde saklanir, kaldigi yerden devam eder.
"""
import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

CKAN = "https://data.gov.ro/api/3/action"
ANAF_BILANT = "https://webservicesp.anaf.ro/bilant"
ANAF_TVA = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
UA = {"User-Agent": "Mozilla/5.0 (firme-5621 open-data script)"}

HERE = Path(__file__).resolve().parent


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def norm(s):
    """Lowercase, no diacritics, single spaces."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_cui(v):
    d = re.sub(r"\D", "", str(v or ""))
    return d.lstrip("0") or None


# --------------------------------------------------------------------------
# 1. ONRC dosyalari (data.gov.ro)
# --------------------------------------------------------------------------

def find_onrc_package():
    """En guncel ONRC firma setini CKAN API ile bulur."""
    r = requests.get(
        f"{CKAN}/package_search",
        params={"q": "firme registrul comertului", "rows": 50, "sort": "metadata_modified desc"},
        headers=UA, timeout=60,
    )
    r.raise_for_status()
    for pkg in r.json()["result"]["results"]:
        names = " ".join(norm(res.get("name") or res.get("url", "")) + " " + norm(res.get("url", ""))
                         for res in pkg["resources"])
        if "od_firme" in names and "caen" in names:
            return pkg
    raise SystemExit(
        "data.gov.ro'da ONRC seti bulunamadi. Dosyalari elle indirip --onrc-dir ile verin:\n"
        "https://data.gov.ro/dataset?q=firme+inregistrate+registrul+comertului"
    )


def download(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  var: {dest.name}")
        return dest
    log(f"  indiriliyor: {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=UA, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


def fetch_onrc(onrc_dir):
    onrc_dir.mkdir(parents=True, exist_ok=True)
    pkg = find_onrc_package()
    log(f"ONRC seti: {pkg['title']}")
    wanted = ("od_firme", "od_caen_autorizat", "od_stare_firma", "n_stare_firma")
    for res in pkg["resources"]:
        url = res.get("url", "")
        fname = url.rsplit("/", 1)[-1] or (res.get("name") or "")
        if any(w in norm(fname) for w in wanted):
            download(url, onrc_dir / fname)


def pick_file(onrc_dir, key):
    files = sorted(p for p in onrc_dir.iterdir()
                   if key in norm(p.name) and not p.name.endswith(".part"))
    return files


def sniff(path):
    """Ayraci ve kodlamayi tahmin eder (ONRC genelde '^' kullanir)."""
    raw = path.open("rb").read(64 * 1024)
    enc = "utf-8-sig"
    try:
        head = raw.decode(enc)
    except UnicodeDecodeError:
        enc, head = "cp1250", raw.decode("cp1250", "replace")
    first = head.splitlines()[0]
    sep = max(["^", ";", "|", "\t", ","], key=first.count)
    return sep, enc


def read_table(path, want):
    """want: {hedef_ad: [olasi kolon adlari / parcalari]} -> DataFrame."""
    sep, enc = sniff(path)
    cols = pd.read_csv(path, sep=sep, encoding=enc, nrows=0, dtype=str,
                       engine="python" if len(sep) > 1 else "c").columns
    ncols = {c: norm(c).replace(" ", "_") for c in cols}
    mapping = {}
    for target, options in want.items():
        for opt in options:
            hit = [c for c, n in ncols.items() if n == opt] or \
                  [c for c, n in ncols.items() if opt in n]
            if hit:
                mapping[hit[0]] = target
                break
    df = pd.read_csv(path, sep=sep, encoding=enc, usecols=list(mapping), dtype=str,
                     quoting=csv.QUOTE_NONE, on_bad_lines="skip")
    return df.rename(columns=mapping)


def onrc_candidates(onrc_dir, caen):
    caen_files = pick_file(onrc_dir, "od_caen_autorizat")
    firme_files = pick_file(onrc_dir, "od_firme")
    if not caen_files or not firme_files:
        raise SystemExit(f"{onrc_dir} icinde od_firme / od_caen_autorizat dosyalari yok.")

    log("ONRC CAEN dosyasi okunuyor...")
    ca = pd.concat(read_table(f, {"reg": ["cod_inmatriculare"],
                                  "caen": ["cod_caen_autorizat", "cod_caen", "caen"]})
                   for f in caen_files)
    ca["caen"] = ca["caen"].str.strip().str.zfill(4)
    regs = set(ca.loc[ca["caen"] == caen, "reg"].str.strip())
    log(f"  CAEN {caen} icin yetkili firma: {len(regs):,}")

    log("ONRC firma dosyasi okunuyor (buyuk dosya, 1-2 dk surebilir)...")
    fi = pd.concat(read_table(f, {
        "reg": ["cod_inmatriculare"], "cui": ["cui", "cod_fiscal"],
        "denumire": ["denumire"], "forma": ["forma_juridica"],
        "judet": ["adr_judet", "judet"], "localitate": ["adr_localitate", "localitate"],
        "data_inm": ["data_inmatriculare"],
    }) for f in firme_files)
    fi["reg"] = fi["reg"].str.strip()
    fi = fi[fi["reg"].isin(regs)].copy()

    # Silinmis (radiata) firmalari ele
    st_files, nst_files = pick_file(onrc_dir, "od_stare_firma"), pick_file(onrc_dir, "n_stare_firma")
    if st_files and nst_files:
        st = pd.concat(read_table(f, {"reg": ["cod_inmatriculare"], "cod": ["cod"]}) for f in st_files)
        nst = pd.concat(read_table(f, {"cod": ["cod"], "den": ["denumire"]}) for f in nst_files)
        dead = set(nst.loc[nst["den"].map(norm).str.contains("radiat|radiere"), "cod"].str.strip())
        dead_regs = set(st.loc[st["cod"].str.strip().isin(dead), "reg"].str.strip())
        before = len(fi)
        fi = fi[~fi["reg"].isin(dead_regs)]
        log(f"  silinmis firmalar cikarildi: {before - len(fi):,}")

    fi["cui"] = fi["cui"].map(clean_cui)
    fi = fi.dropna(subset=["cui"]).drop_duplicates("cui")
    log(f"  aday firma: {len(fi):,}")
    return fi


# --------------------------------------------------------------------------
# 2-3. ANAF API'leri (cache'li, kaldigi yerden devam eder)
# --------------------------------------------------------------------------

class Cache:
    def __init__(self, path):
        self.path, self.data = path, {}
        if path.exists():
            for line in path.open(encoding="utf-8"):
                try:
                    k, v = json.loads(line)
                    self.data[k] = v
                except ValueError:
                    pass
        self.f = path.open("a", encoding="utf-8")

    def __contains__(self, k):
        return k in self.data

    def get(self, k):
        return self.data.get(k)

    def put(self, k, v):
        self.data[k] = v
        self.f.write(json.dumps([k, v], ensure_ascii=False) + "\n")
        self.f.flush()


def http_retry(fn, tries=6):
    delay = 5
    for i in range(tries):
        try:
            r = fn()
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            log(f"    HTTP {r.status_code}, {delay}s bekleniyor")
        except requests.RequestException as e:
            log(f"    ag hatasi ({e.__class__.__name__}), {delay}s bekleniyor")
        time.sleep(delay)
        delay = min(delay * 2, 300)
    return None


def anaf_tva(cuis, cache, pause):
    today = dt.date.today().isoformat()
    todo = [c for c in cuis if c not in cache]
    log(f"ANAF TVA (adres/telefon): {len(todo):,} firma, 100'luk paketler")
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        body = [{"cui": int(c), "data": today} for c in batch]
        r = http_retry(lambda: requests.post(ANAF_TVA, json=body, headers=UA, timeout=60))
        found = {}
        if r is not None:
            try:
                for item in r.json().get("found", []):
                    found[str(item["date_generale"]["cui"])] = item
            except ValueError:
                pass
        for c in batch:
            cache.put(c, found.get(c))
        log(f"  {min(i + 100, len(todo)):,}/{len(todo):,}")
        time.sleep(pause)


def anaf_bilant(cuis, years, cache, pause):
    todo = [c for c in cuis if c not in cache]
    eta = dt.timedelta(seconds=int(len(todo) * (pause + 0.3) * 1.2))
    log(f"ANAF bilanco: {len(todo):,} firma (tahmini sure ~{eta})")
    for n, c in enumerate(todo, 1):
        result = None
        for y in years:
            r = http_retry(lambda: requests.get(ANAF_BILANT, params={"an": y, "cui": c},
                                                headers=UA, timeout=60))
            time.sleep(pause)
            if r is None:
                continue
            try:
                j = r.json()
            except ValueError:
                continue
            if j.get("i"):
                result = j
                break
        cache.put(c, result)
        if n % 50 == 0 or n == len(todo):
            log(f"  {n:,}/{len(todo):,}")


def indicator(bil, *names):
    for it in bil.get("i", []):
        label = norm(it.get("val_den_indicator", ""))
        if any(n in label for n in names):
            return it.get("val_indicator")
    return None


# --------------------------------------------------------------------------
# 4. Excel
# --------------------------------------------------------------------------

def sheet_name(s, used):
    s = re.sub(r"[\[\]:*?/\\]", " ", str(s or "Necunoscut")).strip()[:31] or "Necunoscut"
    base, k = s, 2
    while s.lower() in used:
        suffix = f" ({k})"
        s, k = base[:31 - len(suffix)] + suffix, k + 1
    used.add(s.lower())
    return s


def write_excel(df, out, group_col):
    from openpyxl.utils import get_column_letter

    money = {"Cifra de afaceri (RON)", "Profit net (RON)"}
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        used = set()
        sheets = [("TOATE", df)] + [
            (g, part) for g, part in sorted(df.groupby(group_col, dropna=False),
                                            key=lambda kv: str(kv[0]))
        ]
        for name, part in sheets:
            sn = sheet_name(name, used)
            part.to_excel(xw, sheet_name=sn, index=False)
            ws = xw.sheets[sn]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(part.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in part[col].head(500)])
                ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
                if col in money:
                    for cell in ws[get_column_letter(i)][1:]:
                        cell.number_format = "#,##0"


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--caen", default="5621")
    ap.add_argument("--onrc-dir", type=Path, default=HERE / "onrc",
                    help="ONRC dosyalarinin klasoru (yoksa data.gov.ro'dan indirilir)")
    ap.add_argument("--years", default=None,
                    help="Denenecek bilanco yillari, ornek 2024,2023 (varsayilan: son 2 yil)")
    ap.add_argument("--group", choices=["judet", "localitate"], default="judet",
                    help="Excel'de sayfa bolme: judet (il) veya localitate (sehir/kasaba)")
    ap.add_argument("--pause", type=float, default=1.0, help="ANAF istekleri arasi bekleme (sn)")
    ap.add_argument("--include-other-main-caen", action="store_true",
                    help="Bilancoda ana faaliyeti 5621 olmayanlari da ekle (ayri sutunla)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    this_year = dt.date.today().year
    years = [int(y) for y in args.years.split(",")] if args.years else [this_year - 1, this_year - 2]
    caen = args.caen.zfill(4)

    if not args.onrc_dir.exists() or not pick_file(args.onrc_dir, "od_firme"):
        log("ONRC dosyalari data.gov.ro'dan indiriliyor...")
        fetch_onrc(args.onrc_dir)

    fi = onrc_candidates(args.onrc_dir, caen)
    cuis = fi["cui"].tolist()

    cache_dir = HERE / "cache"
    cache_dir.mkdir(exist_ok=True)
    tva = Cache(cache_dir / "anaf_tva.jsonl")
    bil = Cache(cache_dir / f"anaf_bilant_{'_'.join(map(str, years))}.jsonl")

    anaf_tva(cuis, tva, max(args.pause, 1.0))
    anaf_bilant(cuis, years, bil, args.pause)

    rows = []
    for rec in fi.to_dict("records"):
        c = rec["cui"]
        b = bil.get(c) or {}
        t = tva.get(c) or {}
        g = t.get("date_generale", {}) if t else {}
        sed = t.get("adresa_sediu_social", {}) if t else {}
        raw_caen = str(b.get("caen") or g.get("cod_CAEN") or "").strip()
        main_caen = raw_caen.zfill(4) if raw_caen else ""
        if main_caen != caen and not args.include_other_main_caen:
            continue
        ciro = indicator(b, "cifra de afaceri")
        profit = indicator(b, "profit net", "profitul net")
        loss = indicator(b, "pierdere neta", "pierderea neta")
        if profit in (None, 0) and loss:
            profit = -abs(loss)
        rows.append({
            "Denumire": rec.get("denumire") or g.get("denumire"),
            "CUI": int(c),
            "Nr. Reg. Com.": rec.get("reg"),
            "Judet": (rec.get("judet") or sed.get("sdenumire_Judet") or "").strip().title(),
            "Localitate": (rec.get("localitate") or sed.get("sdenumire_Localitate") or "").strip().title(),
            "Adresa": g.get("adresa"),
            "Telefon": g.get("telefon"),
            "CAEN preponderent": main_caen,
            "Activitate": b.get("den_caen"),
            "An bilant": b.get("an"),
            "Cifra de afaceri (RON)": ciro,
            "Profit net (RON)": profit,
            "Nr. mediu salariati": indicator(b, "numar mediu de salariati", "numarul mediu de salariati"),
            "Forma juridica": rec.get("forma"),
            "Data inmatriculare": rec.get("data_inm"),
            "Stare ANAF": g.get("stare_inregistrare"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("Filtreye uyan firma bulunamadi.")
    df = df[~df["Stare ANAF"].fillna("").map(norm).str.contains("radiere|radiat")]
    df["Cifra de afaceri (RON)"] = pd.to_numeric(df["Cifra de afaceri (RON)"], errors="coerce")
    df = df.sort_values("Cifra de afaceri (RON)", ascending=False, na_position="last")

    group_col = "Judet" if args.group == "judet" else "Localitate"
    out = args.out or HERE / f"firme_caen_{caen}_{dt.date.today():%Y%m%d}.xlsx"
    write_excel(df, out, group_col)
    log(f"Bitti: {len(df):,} firma -> {out}")


if __name__ == "__main__":
    sys.exit(main())
