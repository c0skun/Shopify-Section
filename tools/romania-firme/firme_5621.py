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

Sadece Python standart kutuphanesi + openpyxl kullanir (derlenmis DLL yok,
Windows Smart App Control engellemez).

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
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CKAN = "https://data.gov.ro/api/3/action"
ANAF_BILANT = "https://webservicesp.anaf.ro/bilant"
ANAF_TVA = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
UA = {"User-Agent": "Mozilla/5.0 (firme-5621 open-data script)"}

HERE = Path(__file__).resolve().parent
csv.field_size_limit(10 * 1024 * 1024)


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
# HTTP (urllib, ek paket gerektirmez)
# --------------------------------------------------------------------------

class HttpResult:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def http(method, url, params=None, body=None, timeout=60):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = dict(UA)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return HttpResult(r.status, r.read())
    except urllib.error.HTTPError as e:
        return HttpResult(e.code, e.read() or b"")


def http_retry(fn, tries=6):
    delay = 5
    for _ in range(tries):
        try:
            r = fn()
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            log(f"    HTTP {r.status_code}, {delay}s bekleniyor")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log(f"    ag hatasi ({e.__class__.__name__}), {delay}s bekleniyor")
        time.sleep(delay)
        delay = min(delay * 2, 300)
    return None


# --------------------------------------------------------------------------
# 1. ONRC dosyalari (data.gov.ro)
# --------------------------------------------------------------------------

def find_onrc_package():
    """En guncel ONRC firma setini CKAN API ile bulur."""
    r = http_retry(lambda: http("GET", f"{CKAN}/package_search", params={
        "q": "firme registrul comertului", "rows": 50, "sort": "metadata_modified desc"}))
    if r is None:
        raise SystemExit("data.gov.ro API'sine ulasilamadi.")
    for pkg in r.json()["result"]["results"]:
        names = " ".join(norm(res.get("name") or "") + " " + norm(res.get("url", ""))
                         for res in pkg["resources"])
        if "od_firme" in names and "caen" in names:
            return pkg
    raise SystemExit(
        "data.gov.ro'da ONRC seti bulunamadi. Dosyalari elle indirip --onrc-dir ile verin:\n"
        "https://data.gov.ro/dataset?q=firme+inregistrate+registrul+comertului"
    )


def download(url, dest, tries=5):
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  var: {dest.name}")
        return dest
    log(f"  indiriliyor: {dest.name}")
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done, last, start = 0, 0.0, time.time()
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 5:
                        last = time.time()
                        speed = done / max(last - start, 1) / 1e6
                        pct = f" (%{done * 100 / total:.0f})" if total else ""
                        print(f"\r    {done / 1e6:,.0f} MB{pct}  {speed:.1f} MB/sn   ",
                              end="", flush=True)
            print(f"\r    {done / 1e6:,.0f} MB tamam{' ' * 20}", flush=True)
            tmp.replace(dest)
            return dest
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            print()
            log(f"    indirme hatasi ({e.__class__.__name__}), tekrar deneniyor ({attempt}/{tries})")
            time.sleep(10 * attempt)
    raise SystemExit(f"{dest.name} indirilemedi. Tarayicidan indirip {dest.parent} klasorune koyun:\n{url}")


def fetch_onrc(onrc_dir):
    onrc_dir.mkdir(parents=True, exist_ok=True)
    pkg = find_onrc_package()
    log(f"ONRC seti: {pkg['title']}")
    wanted = ("od_firme", "od_caen_autorizat", "od_stare_firma", "n_stare_firma")
    for res in pkg["resources"]:
        url = res.get("url", "")
        fname = urllib.parse.unquote(url.rsplit("/", 1)[-1]) or (res.get("name") or "")
        if any(w in norm(fname) for w in wanted):
            download(url, onrc_dir / fname)


def pick_file(onrc_dir, key):
    if not onrc_dir.exists():
        return []
    return sorted(p for p in onrc_dir.iterdir()
                  if key in norm(p.name) and not p.name.endswith(".part"))


def sniff(path):
    """Ayraci ve kodlamayi tahmin eder (ONRC genelde '^' kullanir)."""
    with path.open("rb") as f:
        raw = f.read(64 * 1024)
    enc = "utf-8-sig"
    try:
        head = raw.decode(enc)
    except UnicodeDecodeError:
        # sadece son karakter kesilmis olabilir
        try:
            head = raw[:-4].decode(enc)
        except UnicodeDecodeError:
            enc, head = "cp1250", raw.decode("cp1250", "replace")
    first = head.splitlines()[0]
    sep = max(["^", ";", "|", "\t", ","], key=first.count)
    return sep, enc


def read_table(path, want):
    """want: {hedef_ad: [olasi kolon adlari / parcalari]} -> satir dict'leri (generator)."""
    sep, enc = sniff(path)
    with path.open(encoding=enc, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=sep, quoting=csv.QUOTE_NONE)
        header = [norm(c).replace(" ", "_") for c in next(reader)]
        idx = {}
        for target, options in want.items():
            for opt in options:
                hit = [i for i, n in enumerate(header) if n == opt] or \
                      [i for i, n in enumerate(header) if opt in n]
                if hit:
                    idx[target] = hit[0]
                    break
        for row in reader:
            yield {t: (row[i].strip() if i < len(row) else "") for t, i in idx.items()}


def onrc_candidates(onrc_dir, caen):
    caen_files = pick_file(onrc_dir, "od_caen_autorizat")
    firme_files = pick_file(onrc_dir, "od_firme")
    if not caen_files or not firme_files:
        raise SystemExit(f"{onrc_dir} icinde od_firme / od_caen_autorizat dosyalari yok.")

    log("ONRC CAEN dosyasi okunuyor...")
    regs = set()
    for f in caen_files:
        for r in read_table(f, {"reg": ["cod_inmatriculare"],
                                "caen": ["cod_caen_autorizat", "cod_caen", "caen"]}):
            if r.get("caen", "").zfill(4) == caen:
                regs.add(r["reg"])
    log(f"  CAEN {caen} icin yetkili firma: {len(regs):,}")

    dead_regs = set()
    st_files, nst_files = pick_file(onrc_dir, "od_stare_firma"), pick_file(onrc_dir, "n_stare_firma")
    if st_files and nst_files:
        dead = set()
        for f in nst_files:
            for r in read_table(f, {"cod": ["cod"], "den": ["denumire"]}):
                if re.search("radiat|radiere", norm(r.get("den", ""))):
                    dead.add(r["cod"])
        for f in st_files:
            for r in read_table(f, {"reg": ["cod_inmatriculare"], "cod": ["cod"]}):
                if r.get("cod") in dead and r.get("reg") in regs:
                    dead_regs.add(r["reg"])
        log(f"  silinmis firmalar cikarilacak: {len(dead_regs):,}")

    log("ONRC firma dosyasi okunuyor (buyuk dosya, birkac dk surebilir)...")
    firms = {}
    for f in firme_files:
        for r in read_table(f, {
            "reg": ["cod_inmatriculare"], "cui": ["cui", "cod_fiscal"],
            "denumire": ["denumire"], "forma": ["forma_juridica"],
            "judet": ["adr_judet", "judet"], "localitate": ["adr_localitate", "localitate"],
            "data_inm": ["data_inmatriculare"],
        }):
            if r.get("reg") not in regs or r["reg"] in dead_regs:
                continue
            cui = clean_cui(r.get("cui"))
            if cui and cui not in firms:
                r["cui"] = cui
                firms[cui] = r
    log(f"  aday firma: {len(firms):,}")
    return list(firms.values())


# --------------------------------------------------------------------------
# 2-3. ANAF API'leri (cache'li, kaldigi yerden devam eder)
# --------------------------------------------------------------------------

class Cache:
    def __init__(self, path):
        self.data = {}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
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


def anaf_tva(cuis, cache, pause):
    today = dt.date.today().isoformat()
    todo = [c for c in cuis if c not in cache]
    log(f"ANAF TVA (adres/telefon): {len(todo):,} firma, 100'luk paketler")
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        body = [{"cui": int(c), "data": today} for c in batch]
        r = http_retry(lambda: http("POST", ANAF_TVA, body=body))
        found = {}
        if r is not None:
            try:
                for item in r.json().get("found", []):
                    found[str(item["date_generale"]["cui"])] = item
            except (ValueError, KeyError, TypeError):
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
            r = http_retry(lambda: http("GET", ANAF_BILANT, params={"an": y, "cui": c}))
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


def to_num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 4. Excel (openpyxl, saf Python)
# --------------------------------------------------------------------------

COLUMNS = ["Denumire", "CUI", "Nr. Reg. Com.", "Judet", "Localitate", "Adresa", "Telefon",
           "CAEN preponderent", "Activitate", "An bilant", "Cifra de afaceri (RON)",
           "Profit net (RON)", "Nr. mediu salariati", "Forma juridica", "Data inmatriculare",
           "Stare ANAF"]
MONEY = {"Cifra de afaceri (RON)", "Profit net (RON)"}


def sheet_name(s, used):
    s = re.sub(r"[\[\]:*?/\\]", " ", str(s or "Necunoscut")).strip()[:31] or "Necunoscut"
    base, k = s, 2
    while s.lower() in used:
        suffix = f" ({k})"
        s, k = base[:31 - len(suffix)] + suffix, k + 1
    used.add(s.lower())
    return s


def write_excel(rows, out, group_col):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    groups = {}
    for r in rows:
        groups.setdefault(r[group_col] or "Necunoscut", []).append(r)

    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    for name, part in [("TOATE", rows)] + sorted(groups.items(), key=lambda kv: norm(kv[0])):
        ws = wb.create_sheet(sheet_name(name, used))
        ws.append(COLUMNS)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in part:
            ws.append([r.get(col) for col in COLUMNS])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(COLUMNS, 1):
            letter = get_column_letter(i)
            width = max([len(col)] + [len(str(r.get(col) or "")) for r in part[:500]])
            ws.column_dimensions[letter].width = min(max(width + 2, 8), 60)
            if col in MONEY:
                for cell in ws[letter][1:]:
                    cell.number_format = "#,##0"
    wb.save(out)


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
                    help="Bilancoda ana faaliyeti 5621 olmayanlari da ekle")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    this_year = dt.date.today().year
    years = [int(y) for y in args.years.split(",")] if args.years else [this_year - 1, this_year - 2]
    caen = args.caen.zfill(4)

    if not pick_file(args.onrc_dir, "od_firme"):
        log("ONRC dosyalari data.gov.ro'dan indiriliyor...")
        fetch_onrc(args.onrc_dir)

    firms = onrc_candidates(args.onrc_dir, caen)
    cuis = [f["cui"] for f in firms]

    cache_dir = HERE / "cache"
    cache_dir.mkdir(exist_ok=True)
    tva = Cache(cache_dir / "anaf_tva.jsonl")
    bil = Cache(cache_dir / f"anaf_bilant_{'_'.join(map(str, years))}.jsonl")

    anaf_tva(cuis, tva, max(args.pause, 1.0))
    anaf_bilant(cuis, years, bil, args.pause)

    rows = []
    for rec in firms:
        c = rec["cui"]
        b = bil.get(c) or {}
        t = tva.get(c) or {}
        g = t.get("date_generale") or {}
        sed = t.get("adresa_sediu_social") or {}
        raw_caen = str(b.get("caen") or g.get("cod_CAEN") or "").strip()
        main_caen = raw_caen.zfill(4) if raw_caen else ""
        if main_caen != caen and not args.include_other_main_caen:
            continue
        stare = g.get("stare_inregistrare") or ""
        if re.search("radiere|radiat", norm(stare)):
            continue
        profit = to_num(indicator(b, "profit net", "profitul net"))
        loss = to_num(indicator(b, "pierdere neta", "pierderea neta"))
        if not profit and loss:
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
            "Cifra de afaceri (RON)": to_num(indicator(b, "cifra de afaceri")),
            "Profit net (RON)": profit,
            "Nr. mediu salariati": to_num(indicator(b, "numar mediu de salariati", "numarul mediu de salariati")),
            "Forma juridica": rec.get("forma"),
            "Data inmatriculare": rec.get("data_inm"),
            "Stare ANAF": stare,
        })

    if not rows:
        raise SystemExit("Filtreye uyan firma bulunamadi.")
    rows.sort(key=lambda r: (r["Cifra de afaceri (RON)"] is None, -(r["Cifra de afaceri (RON)"] or 0)))

    group_col = "Judet" if args.group == "judet" else "Localitate"
    out = args.out or HERE / f"firme_caen_{caen}_{dt.date.today():%Y%m%d}.xlsx"
    write_excel(rows, out, group_col)
    log(f"Bitti: {len(rows):,} firma -> {out}")


if __name__ == "__main__":
    sys.exit(main())
