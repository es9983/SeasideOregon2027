import json, os, re, smtplib, hashlib
from pathlib import Path
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CONFIG = json.loads((ROOT / "config.json").read_text())
HISTORY_FILE = DATA / "history.json"
LATEST_FILE = DATA / "latest.json"
REPORT_FILE = DATA / "report.txt"

def load_json(path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text())
    except Exception: return default

def money(text):
    if not text: return None
    m = re.search(r"\$[\d,]+(?:\.\d{1,2})?", text.replace("\xa0"," "))
    return m.group(0) if m else None

def make_id(site, text):
    return hashlib.sha256(f"{site}|{text}".encode()).hexdigest()[:16]

def collect_redweek(page):
    # Search the resort page. RedWeek's HTML has historically exposed rental cards,
    # but selectors can change. Do not bypass login/CAPTCHA.
    url = "https://www.redweek.com/resort/P4912-worldmark-seaside/timeshare-rentals"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    results = []
    # Conservative extraction: look for blocks containing 2027 dates and WorldMark context.
    for block in soup.find_all(["article","li","div"]):
        t = block.get_text(" ", strip=True)
        if "2027" not in t or "$" not in t or not re.search(r"(Jul|July)", t, re.I):
            continue
        if not re.search(r"(7 nights|7 Night|WorldMark)", t, re.I):
            continue
        if len(t) > 1500: continue
        results.append({
            "site":"redweek",
            "listing_id":make_id("redweek", t[:1000]),
            "title":"WorldMark Seaside",
            "details":t[:1000],
            "price":money(t),
            "url":url
        })
    return dedupe(results)

def collect_koala(page):
    # Go-Koala resort page. Search UI/HTML may change; this collector is intentionally
    # conservative and does not attempt to defeat anti-bot controls.
    url = "https://www.go-koala.com/resort/worldmark-seaside"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    soup = BeautifulSoup(page.content(), "html.parser")
    results = []
    for block in soup.find_all(["article","li","div"]):
        t = block.get_text(" ", strip=True)
        if "$" not in t or len(t) > 1500: continue
        if not re.search(r"(WorldMark|Seaside)", t, re.I): continue
        # Keep only blocks that look like inventory cards.
        if not re.search(r"(night|week|bed|sleep|guest|available)", t, re.I): continue
        results.append({
            "site":"go-koala",
            "listing_id":make_id("go-koala", t[:1000]),
            "title":"WorldMark Seaside",
            "details":t[:1000],
            "price":money(t),
            "url":url
        })
    return dedupe(results)

def dedupe(items):
    out, seen = [], set()
    for x in items:
        k=(x["site"], x["listing_id"])
        if k not in seen:
            seen.add(k); out.append(x)
    return out

def run():
    history=load_json(HISTORY_FILE, [])
    previous=history[-1]["listings"] if history else []
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=CONFIG.get("headless", True))
        page=browser.new_page(
            user_agent="Mozilla/5.0 (compatible; WorldMarkSeasideWatcher/1.0)"
        )
        all_results=[]
        errors=[]
        for site, fn in [("go-koala",collect_koala),("redweek",collect_redweek)]:
            try:
                all_results += fn(page)
            except Exception as e:
                errors.append(f"{site}: {type(e).__name__}: {e}")
        browser.close()

    # Since public pages may show multiple date ranges, keep records containing the target
    # date/year text when possible. If date extraction is unavailable, label as unverified.
    target_year="2027"
    target_month="Jul"
    target=[]
    for r in all_results:
        d=r["details"]
        if target_year in d and re.search(target_month, d, re.I):
            r["date_match"]="possible"
            target.append(r)

    now=datetime.now(timezone.utc).isoformat()
    snapshot={"checked_at":now,"listings":target,"errors":errors}
    history.append(snapshot)
    HISTORY_FILE.write_text(json.dumps(history[-90:], indent=2))
    LATEST_FILE.write_text(json.dumps(snapshot, indent=2))

    prev_by={x["listing_id"]:x for x in previous}
    curr_by={x["listing_id"]:x for x in target}
    changes=[]
    for k,v in curr_by.items():
        if k not in prev_by:
            changes.append(("NEW",v))
        elif v.get("price") != prev_by[k].get("price"):
            changes.append(("PRICE CHANGE",v))
    for k,v in prev_by.items():
        if k not in curr_by:
            changes.append(("REMOVED/NO LONGER FOUND",v))

    lines=[
        f"WorldMark Seaside — {CONFIG['check_in']} to {CONFIG['check_out']}",
        f"Checked: {now}",
        "",
        "CURRENT LISTINGS"
    ]
    if target:
        for x in target:
            lines += [f"- {x['site']} | {x['price'] or 'price not extracted'} | {x['details']} | {x['url']}"]
    else:
        lines.append("- No listings confidently matching the target date range were extracted.")
    if errors:
        lines += ["","COLLECTOR ERRORS"] + [f"- {e}" for e in errors]
    REPORT_FILE.write_text("\n".join(lines))

    if changes or (target and not previous):
        send_email("\n".join(lines), changes)

def send_email(report, changes):
    host=os.environ.get("SMTP_HOST")
    port=int(os.environ.get("SMTP_PORT","465"))
    user=os.environ.get("SMTP_USERNAME")
    password=os.environ.get("SMTP_PASSWORD")
    to=os.environ.get("ALERT_EMAIL")
    if not all([host,user,password,to]):
        print("Email secrets not configured; report saved locally.")
        return
    subject="WorldMark Seaside: availability/price update"
    if changes:
        subject += f" ({len(changes)} change(s))"
    msg=EmailMessage()
    msg["From"]=user; msg["To"]=to; msg["Subject"]=subject
    msg.set_content(report)
    with smtplib.SMTP_SSL(host,port) as s:
        s.login(user,password)
        s.send_message(msg)

if __name__=="__main__":
    run()
