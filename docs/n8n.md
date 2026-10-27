# Run it in n8n

[`n8n/ai-lead-enrichment.json`](../n8n/ai-lead-enrichment.json) is the same enrichment for n8n. Every morning it finds the HubSpot contacts with no email or no job title, runs them through the Evaboot waterfall, lets Claude judge them, and updates each contact.

## What runs

1. **Every morning at 7** and **Settings**: how many days back, how many contacts, and who fits.
2. **Contacts to enrich** (HubSpot search): no email or no job title, never enriched, created in the last `since_days`.
3. **Has a Sales Navigator id**: a `/sales/lead/` URL or an `ACw...` id in `hs_linkedin_url`.
4. **Evaboot profile export** and **Read the profile**: title, company data and a verified email. **Still needs an email** sends a contact the profile did not complete to the finder.
5. **Needs the finder**, **Evaboot email finder** and **Read the email**: name + company in, email and its status out.
6. **All contacts** and **Judge with Claude**: a job function, a seniority, a fit and one summary line per contact.
7. **Check and build the update** and **Update the contact**: only empty fields are written, and an email only when Evaboot rates it safe and it is on the company's domain.

## Set it up

1. **Create three contact properties in HubSpot** (*Settings > Properties > Create property*): `ai_enrichment_status` (dropdown: enriched, email_only, not_found), `ai_enrichment_summary` (multi-line text) and `ai_enriched_at` (date picker).
2. **Import** the JSON in n8n: *Workflows > Import from file*.
3. **Add three credentials:**
   - **HubSpot App Token** on Contacts to enrich and Update the contact: a private app or service key with `crm.objects.contacts.read` and `crm.objects.contacts.write`.
   - **Header Auth** named Evaboot API on both Evaboot nodes: name `Authorization`, value `Bearer <your Evaboot API key>`.
   - **Anthropic** on the Claude node.
4. **Fill in Settings:** `since_days`, `limit`, and `buyers`, who fits for you.
5. **Test:** click **Execute workflow**, then open a contact in HubSpot.
6. **Publish** the workflow so it runs every morning.

## Good to know

- Each profile export costs 1 Evaboot credit; each email found costs 1. A contact is never enriched twice: `ai_enrichment_status` takes it out of the search.
- Evaboot's profile export needs the Sales Navigator id. Contacts you send to HubSpot from Evaboot already carry it; a public `linkedin.com/in/<name>` URL goes to the email finder instead.
- HubSpot's search can take a minute to see a contact created a moment ago.

Back to the [README](../README.md).
