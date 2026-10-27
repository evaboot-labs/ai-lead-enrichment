# Connect your agent by hand

The prompt in the README does all of this for you. These are the same steps, for when you want to do them yourself.

1. **Create your Evaboot account** at [dash.evaboot.com](https://dash.evaboot.com/accounts/signup/?last_click_origin=ai-lead-enrichment-repo). The email finder works without Sales Navigator; the profile export needs the [Chrome extension](https://dash.evaboot.com/install/) and an active Sales Navigator seat.
2. **Get the repo:**
   ```bash
   git clone https://github.com/evaboot-labs/ai-lead-enrichment.git
   cd ai-lead-enrichment
   ```
3. **Add your keys.** Copy your Evaboot API key from [dash.evaboot.com/dash/api/](https://dash.evaboot.com/dash/api/). In HubSpot, create a private app or a service key with the scopes `crm.objects.contacts.read`, `crm.objects.contacts.write` and `crm.schemas.contacts.write`. Then:
   ```bash
   cp .env.example .env          # paste both keys
   ```
4. **Create the three HubSpot properties** the workflow writes, once:
   ```bash
   set -a; . ./.env; set +a
   for body in \
     '{"name":"ai_enrichment_status","label":"AI enrichment status","type":"enumeration","fieldType":"select","groupName":"contactinformation","options":[{"label":"Enriched","value":"enriched"},{"label":"Email only","value":"email_only"},{"label":"Not found","value":"not_found"}]}' \
     '{"name":"ai_enrichment_summary","label":"AI enrichment summary","type":"string","fieldType":"textarea","groupName":"contactinformation"}' \
     '{"name":"ai_enriched_at","label":"AI enriched at","type":"date","fieldType":"date","groupName":"contactinformation"}'; do
     curl -s -X POST https://api.hubapi.com/crm/v3/properties/contacts -H "Authorization: Bearer $HUBSPOT_TOKEN" \
       -H 'Content-Type: application/json' -d "$body"; echo; done
   ```
5. **Describe who fits** in [`FIT.md`](../FIT.md), or let your agent ask you.
6. **Check** (Python 3.9+, no packages to install): `python3 enrich.py -h` lists the commands.

Then ask your agent: **"Enrich my new HubSpot contacts."**

The repo also ships `.mcp.json` for the Evaboot MCP server (`https://mcp.evaboot.com/mcp`), so your agent can build a Sales Navigator search or export a list in the same session. `enrich.py` does not need it.

Back to the [README](../README.md).
