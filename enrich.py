"""AI lead enrichment for HubSpot: an Evaboot waterfall, then your AI Agent's judgment, then a careful write-back.

    python3 enrich.py pull [--since-days 7] [--limit 50] > queue/contacts.json
        contacts with no email or no job title that were never enriched
    python3 enrich.py evaboot queue/contacts.json > queue/enriched.json
        the waterfall: Sales Navigator profile export when the contact has a Sales Navigator id,
        else (or when it fails) the email finder on name + company
    python3 enrich.py check queue/enriched.json queue/judged.json
        your agent's job function, seniority, fit and summary for each contact
    python3 enrich.py review queue/enriched.json queue/judged.json
        what will change in HubSpot, field by field
    python3 enrich.py push queue/enriched.json queue/judged.json [--apply]
        writes only empty fields (and the ai_* fields); dry run unless --apply

Needs EVABOOT_API_KEY and HUBSPOT_TOKEN in the environment or in .env. Python 3.9+, no packages.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

EVABOOT = "https://api.evaboot.com/v1"
HUBSPOT = "https://api.hubapi.com/crm/v3/objects/contacts"
PROPS = ["firstname", "lastname", "email", "jobtitle", "company", "website", "hs_linkedin_url",
         "job_function", "hs_seniority", "ai_enrichment_status", "createdate"]
SENIORITY = {"owner", "partner", "executive", "vp", "director", "manager", "senior", "entry", "employee"}
FITS = {"good", "maybe", "no"}
MAX_WORDS = 30
GENDERED = re.compile(r"\b(he|she|him|her|his|hers)\b", re.I)


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    if os.path.exists(".env"):
        m = re.search(rf"^{name}=(.*)$", open(".env").read(), re.M)
        if m and m.group(1).strip():
            return m.group(1).strip().strip("'\"")
    sys.exit(f"{name} is missing: add it to .env")


def call(method, url, token, body=None, timeout=90):
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": "evaboot-labs-ai-lead-enrichment"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


# ---------------------------------------------------------------- pull

def pull(since_days, limit):
    since = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp() * 1000)
    common = [{"propertyName": "ai_enrichment_status", "operator": "NOT_HAS_PROPERTY"},
              {"propertyName": "createdate", "operator": "GTE", "value": str(since)}]
    body = {"limit": min(limit, 100), "properties": PROPS, "filterGroups": [
        {"filters": [{"propertyName": "email", "operator": "NOT_HAS_PROPERTY"}, *common]},
        {"filters": [{"propertyName": "jobtitle", "operator": "NOT_HAS_PROPERTY"}, *common]}]}
    status, d = call("POST", f"{HUBSPOT}/search", env("HUBSPOT_TOKEN"), body)
    if status != 200:
        sys.exit(f"HubSpot search failed ({status}): {d.get('message')}")
    out = [{"id": r["id"], **{k: (r["properties"].get(k) or "") for k in PROPS}} for r in d.get("results", [])]
    print(f"{len(out)} contacts to enrich (of {d.get('total', 0)} matching)", file=sys.stderr)
    return out[:limit]


# ---------------------------------------------------------------- evaboot waterfall

def sn_id(url):
    """The Sales Navigator id Evaboot needs: a /sales/lead/ URL or an ACw... member id. A public /in/ name is not one."""
    m = re.search(r"(?:/sales/lead/|/in/)(ACw[\w-]+)", url or "") or re.search(r"/sales/lead/([^,/?]+)", url or "")
    return m.group(1) if m else None


def poll(path, key, ok_status=("complete", "failed", "EXECUTED")):
    for _ in range(40):
        time.sleep(3)
        status, d = call("GET", f"{EVABOOT}/{path}", key)
        if status == 200:
            return d
    return {}


def profile(contact, key):
    status, d = call("POST", f"{EVABOOT}/extractions/single/", key, {"profile_id": contact["hs_linkedin_url"]})
    if status == 202 and d.get("extraction_id"):
        d = poll(f"extractions/{d['extraction_id']}/", key)
        d = {"prospect": (d.get("prospects") or [None])[0]}
    p = d.get("prospect") if isinstance(d, dict) else None
    if not p:
        return None, (d.get("error") or {}).get("message", f"HTTP {status}") if isinstance(d, dict) else f"HTTP {status}"
    years, months = p.get("Years in Position"), p.get("Months in Position")
    try:
        in_role = int(float(years or 0) * 12 + float(months or 0)) if (years or months) else None
    except ValueError:
        in_role = None
    return {"email": p.get("Email") or "", "email_status": (p.get("Email Status") or "").lower(),
            "title": " ".join((p.get("Current Job") or "").split()), "company": p.get("Company Name") or "",
            "company_domain": p.get("Company Domain") or "", "employees": p.get("Company Employee Range") or "",
            "industry": p.get("Company Industry") or "", "growth_1y_pct": p.get("Company Employee Growth 1 Year (%)") or "",
            "months_in_role": in_role, "headline": " ".join((p.get("Profile Headline") or "").split())[:160],
            "linkedin": p.get("Linkedin URL Public") or ""}, None


def finder(contact, key):
    body = {"first_name": contact["firstname"], "last_name": contact["lastname"]}
    if contact["company"]:
        body["company_name"] = contact["company"]
    domain = re.sub(r"^https?://(www\.)?", "", contact["website"] or "").split("/")[0]
    if domain:
        body["company_domain"] = domain
    if not (body["first_name"] and body["last_name"] and (contact["company"] or domain)):
        return None, "needs first name, last name and a company or domain"
    status, d = call("POST", f"{EVABOOT}/email-finder/single/", key, body)
    if status == 202 and d.get("job_id"):
        d = poll(f"email-finder/{d['job_id']}/", key)
        d = {"prospect": (d.get("prospects") or [None])[0]}
    p = (d or {}).get("prospect") or {}
    if not p.get("found_email"):
        return None, p.get("error_message") or "no email found"
    return {"email": p["found_email"], "email_status": (p.get("email_validity") or "").lower(),
            "company_domain": p.get("company_domain") or domain}, None


def evaboot(contacts):
    key = env("EVABOOT_API_KEY")
    out = []
    for c in contacts:
        row = {"id": c["id"], "crm": c, "found": {}, "steps": []}
        if c["hs_linkedin_url"] and not sn_id(c["hs_linkedin_url"]):
            row["steps"].append("profile: skipped, a public LinkedIn URL is not a Sales Navigator id")
        if sn_id(c["hs_linkedin_url"]):
            found, err = profile(c, key)
            row["steps"].append(f"profile: {'ok' if found else err}")
            if found:
                row["found"] = found
        if not row["found"].get("email"):
            found, err = finder(c, key)
            row["steps"].append(f"email finder: {'ok' if found else err}")
            if found:
                row["found"] = {**row["found"], **found}
        f = row["found"]
        row["status"] = "enriched" if f.get("title") else ("email_only" if f.get("email") else "not_found")
        out.append(row)
        print(f"{c['firstname']} {c['lastname'][:1]}. ({c['company']}): {row['status']} - {'; '.join(row['steps'])}",
              file=sys.stderr)
    counts = {s: sum(r["status"] == s for r in out) for s in ("enriched", "email_only", "not_found")}
    print(f"{len(out)} contacts: {counts['enriched']} enriched, {counts['email_only']} email only, "
          f"{counts['not_found']} not found", file=sys.stderr)
    return out


# ---------------------------------------------------------------- check, review, push

def load(enriched_path, judged_path):
    return ({r["id"]: r for r in json.load(open(enriched_path))},
            {j.get("id"): j for j in json.load(open(judged_path))})


def check(enriched_path, judged_path):
    """Every contact with something found gets a fit, a summary, and when a title is known, a function and a
    seniority from HubSpot's list. Returns the problems found."""
    rows, judged = load(enriched_path, judged_path)
    problems = []
    for rid, r in rows.items():
        name = f"{r['crm']['firstname']} {r['crm']['lastname']}".strip()
        j = judged.get(rid)
        if r["status"] == "not_found":
            continue
        if not j:
            problems.append(f"{name}: no judgment")
            continue
        title = r["found"].get("title") or r["crm"]["jobtitle"]
        if title and not j.get("job_function"):
            problems.append(f"{name}: job_function missing for title '{title}'")
        if title and j.get("seniority") not in SENIORITY:
            problems.append(f"{name}: seniority must be one of {', '.join(sorted(SENIORITY))}")
        if j.get("fit") not in FITS:
            problems.append(f"{name}: fit must be good, maybe or no")
        s = j.get("summary") or ""
        if not s or len(s.split()) > MAX_WORDS:
            problems.append(f"{name}: summary is missing or longer than {MAX_WORDS} words")
        if GENDERED.search(s):
            problems.append(f"{name}: summary guesses a gender, use the first name, they or the role")
    for jid in set(judged) - set(rows):
        problems.append(f"unknown contact {jid}")
    return problems


def domain(v):
    return re.sub(r"^https?://(www\.)?", "", (v or "").strip().lower()).split("/")[0]


def email_held(crm, found):
    """An email on another domain than the company website is held for a person to check: the mailbox exists,
    but it may belong to another organisation with a similar name."""
    site = domain(crm.get("website")) or domain(found.get("company_domain"))
    mail = (found.get("email") or "").lower().rsplit("@", 1)[-1]
    if site and mail and "@" in (found.get("email") or "") and not (mail == site or mail.endswith("." + site)):
        return f"{found['email']} is not on {site}"
    return ""


def updates(enriched_path, judged_path):
    """HubSpot properties per contact. A field the CRM already holds is never overwritten; an email is written
    only when Evaboot rates it safe."""
    rows, judged = load(enriched_path, judged_path)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for rid, r in rows.items():
        crm, f, j = r["crm"], r["found"], judged.get(rid) or {}
        props = {"ai_enrichment_status": r["status"], "ai_enriched_at": str(int(today.timestamp() * 1000))}
        held = email_held(crm, f)
        if f.get("email") and not crm["email"] and f.get("email_status") == "safe" and not held:
            props["email"] = f["email"]
        if f.get("title") and not crm["jobtitle"]:
            props["jobtitle"] = f["title"]
        if f.get("linkedin") and not crm["hs_linkedin_url"]:
            props["hs_linkedin_url"] = f["linkedin"]
        if f.get("company_domain") and not crm["website"]:
            props["website"] = f["company_domain"]
        if j.get("job_function") and not crm["job_function"]:
            props["job_function"] = j["job_function"]
        if j.get("seniority") in SENIORITY and not crm["hs_seniority"]:
            props["hs_seniority"] = j["seniority"]
        if j.get("summary") or held:
            props["ai_enrichment_summary"] = f"[{j.get('fit', 'maybe')}] {j.get('summary', '')}".strip() + (
                f" Email held: {held}" if held else "")
        out.append({"id": rid, "name": f"{crm['firstname']} {crm['lastname']}".strip(), "properties": props})
    return out


def review(enriched_path, judged_path):
    lines = []
    for u in updates(enriched_path, judged_path):
        p = u["properties"]
        lines.append(f"{u['name']}: {p['ai_enrichment_status']}")
        for k, v in p.items():
            if k not in ("ai_enrichment_status", "ai_enriched_at"):
                lines.append(f"  {k}: {v}")
    return "\n".join(lines) + "\n"


def push(enriched_path, judged_path, apply):
    ups = updates(enriched_path, judged_path)
    fields = sum(len(u["properties"]) - 2 for u in ups)
    if not apply:
        print(f"dry run: {len(ups)} contacts, {fields} fields to write. Add --apply to write them.")
        return
    status, d = call("POST", f"{HUBSPOT}/batch/update", env("HUBSPOT_TOKEN"),
                     {"inputs": [{"id": u["id"], "properties": u["properties"]} for u in ups]})
    if status not in (200, 207):
        sys.exit(f"HubSpot update failed ({status}): {d.get('message')}")
    print(f"updated {len(d.get('results', []))} contacts, {fields} fields")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--since-days", type=int, default=7)
    p.add_argument("--limit", type=int, default=50)
    e = sub.add_parser("evaboot")
    e.add_argument("contacts")
    for name in ("check", "review", "push"):
        s = sub.add_parser(name)
        s.add_argument("enriched")
        s.add_argument("judged")
        if name == "push":
            s.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.cmd == "pull":
        json.dump(pull(a.since_days, a.limit), sys.stdout, indent=1, ensure_ascii=False)
        print()
    elif a.cmd == "evaboot":
        json.dump(evaboot(json.load(open(a.contacts))), sys.stdout, indent=1, ensure_ascii=False)
        print()
    elif a.cmd == "check":
        problems = check(a.enriched, a.judged)
        for p in problems:
            print("FAIL", p)
        print("OK" if not problems else f"{len(problems)} problem(s)")
        sys.exit(1 if problems else 0)
    elif a.cmd == "review":
        sys.stdout.write(review(a.enriched, a.judged))
    else:
        push(a.enriched, a.judged, a.apply)


if __name__ == "__main__":
    main()
