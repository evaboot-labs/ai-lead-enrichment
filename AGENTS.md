# Agent instructions

This repo is AI lead enrichment for HubSpot. It finds the contacts with no email or no job title, completes them through Evaboot (a Sales Navigator profile export when the contact has a Sales Navigator id, else the email finder on name and company), adds a job function, a seniority, a fit and a one-line summary, and writes back only the fields the CRM does not already hold. When the user asks to enrich leads, complete CRM contacts, or find missing emails and titles:

1. Follow the skill in `skills/ai-lead-enrichment/SKILL.md` step by step.
2. Read `FIT.md` for the buyers and the field rules. If it says `Status: EXAMPLE`, ask the user and update it.
3. Use `enrich.py` for every HubSpot and Evaboot call. It needs `EVABOOT_API_KEY` and `HUBSPOT_TOKEN` in `.env`.
4. If the user is not connected yet, follow `docs/connect-your-agent.md` with them.
5. If the user wants n8n instead, follow `docs/n8n.md` with them one step at a time: you cannot click inside n8n, so say exactly what to do and wait for their confirmation.

Each profile export costs 1 Evaboot credit, each email found costs 1. Show the count and confirm before `enrich.py evaboot`. Never write to HubSpot before the user has read `enrich.py review` and said yes. Never ask for or handle an API key: the user writes it into `.env`. Never commit `.env`, `data/` or `queue/`: they hold real people's data.
