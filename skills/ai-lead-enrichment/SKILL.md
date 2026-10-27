---
name: ai-lead-enrichment
description: Enrich HubSpot contacts with AI - find the contacts with no email or no job title, complete them through Evaboot (Sales Navigator profile export for title, company data and a verified email; email finder on name + company as the fallback), add a job function, a seniority, a fit and a one-line summary, and write back only the fields the CRM does not already hold. Use when the user asks for lead enrichment, CRM enrichment, finding missing emails or job titles, or an AI enrichment workflow for HubSpot.
---

# AI lead enrichment

This skill runs inside a clone of https://github.com/evaboot-labs/ai-lead-enrichment: it uses the repo's `enrich.py`, `FIT.md` and `docs/`. If `enrich.py` is not in the working directory, clone the repo and work from there.

`enrich.py` does every HubSpot and Evaboot call. You judge each enriched contact. Nothing is written to HubSpot before the user says yes.

## Rules

- **Never overwrite what the CRM holds.** `enrich.py push` fills empty fields only (plus the `ai_*` fields); do not work around it.
- Confirm before `enrich.py evaboot`: show how many contacts it will try and the cost (1 Evaboot credit per profile export, 1 per email found).
- Judge each contact only from its row in `queue/enriched.json` and `FIT.md`. Never invent a title, a company fact or a fit.
- Never ask for or paste a key. The user writes `EVABOOT_API_KEY` and `HUBSPOT_TOKEN` into `.env` (`docs/connect-your-agent.md`).

## Step 0: check the setup

1. Run `python3 enrich.py -h`. If `.env` misses a key, walk the user through `docs/connect-your-agent.md`.
2. HubSpot needs three contact properties: `ai_enrichment_status` (dropdown: enriched, email_only, not_found), `ai_enrichment_summary` (multi-line text) and `ai_enriched_at` (date). `docs/connect-your-agent.md` has the call that creates them; ask before you run it.
3. Run `mkdir -p data queue`.
4. Read `FIT.md`. If it says `Status: EXAMPLE`, ask the user who they sell to and who is not a fit. Rewrite the file and set `Status: yours`.

## Step 1: the contacts to enrich

```bash
python3 enrich.py pull --since-days 7 --limit 50 > queue/contacts.json
```

It returns the contacts created in the last 7 days with no email or no job title that were never enriched. HubSpot's search can take a minute to see a contact created a moment ago.

## Step 2: the Evaboot waterfall

Tell the user how many contacts have a Sales Navigator id in `hs_linkedin_url` (a `/sales/lead/` URL or an `ACw...` id) and how many will go straight to the email finder. On a yes:

```bash
python3 enrich.py evaboot queue/contacts.json > queue/enriched.json
```

- A contact with a Sales Navigator id gets the profile export: title, months in role, company size, industry, growth, LinkedIn URL and a verified email.
- A public `linkedin.com/in/<name>` URL is **not** a Sales Navigator id: Evaboot refuses it, so the contact goes to the email finder.
- The email finder needs a first name, a last name and a company name or website. It returns an email and its status, nothing else.

## Step 3: judge

Write `queue/judged.json`, one entry per contact that is not `not_found`:

```json
{"id": "<HubSpot id>", "job_function": "Sales", "seniority": "director", "fit": "good", "summary": "one line"}
```

Follow the field rules in `FIT.md`. Without a title, leave `job_function` and `seniority` out and say so in the summary.

```bash
python3 enrich.py check queue/enriched.json queue/judged.json
python3 enrich.py review queue/enriched.json queue/judged.json
```

Fix every `FAIL`, then show the review. An email on another domain than the company's website is **held**: the review shows it in the summary and it is not written. Point those out.

## Step 4: write back

On the user's yes:

```bash
python3 enrich.py push queue/enriched.json queue/judged.json --apply
```

To run it every morning without an agent, set up the n8n version (`docs/n8n.md`).
