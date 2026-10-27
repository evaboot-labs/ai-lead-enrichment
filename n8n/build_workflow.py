"""Builds n8n/ai-lead-enrichment.json. Run: python3 n8n/build_workflow.py

Every morning: the HubSpot contacts with no email or no job title that were never enriched go through the
Evaboot waterfall (Sales Navigator profile export when the contact has a Sales Navigator id, else or when it
finds no email, the email finder), Claude adds the job function, the seniority, a fit and a summary, and each
contact is updated in HubSpot. Same rules as enrich.py: never overwrite a field the CRM holds, write an email
only when Evaboot rates it safe and it is on the company's domain.
"""
import json
import uuid
from pathlib import Path

ANTHROPIC_CRED = {"anthropicApi": {"id": "", "name": "Anthropic"}}
EVABOOT_CRED = {"httpHeaderAuth": {"id": "", "name": "Evaboot API"}}
HUBSPOT_CRED = {"hubspotAppToken": {"id": "", "name": "HubSpot"}}
MODEL = "claude-sonnet-5-5"
PROPS = ["firstname", "lastname", "email", "jobtitle", "company", "website", "hs_linkedin_url",
         "job_function", "hs_seniority"]

nodes, connections = [], {}


def node(name, type_, version, params, pos, creds=None, **extra):
    n = {"parameters": params, "id": str(uuid.uuid4()), "name": name, "type": type_,
         "typeVersion": version, "position": pos, **extra}
    if creds:
        n["credentials"] = creds
    nodes.append(n)


def link(a, b, kind="main", out=0):
    connections.setdefault(a, {}).setdefault(kind, [])
    while len(connections[a][kind]) <= out:
        connections[a][kind].append([])
    connections[a][kind][out].append({"node": b, "type": kind, "index": 0})


def code(name, js, pos, **extra):
    node(name, "n8n-nodes-base.code", 2, {"jsCode": js}, pos, **extra)


def http(name, method, url, body_expr, pos, cred, **extra):
    p = {"method": method, "url": url, "sendBody": True, "specifyBody": "json", "jsonBody": body_expr,
         "options": {"timeout": 90000, "response": {"response": {"neverError": True, "fullResponse": True}}}}
    if "hubspot" in cred:
        p.update({"authentication": "predefinedCredentialType", "nodeCredentialType": "hubspotAppToken"})
        creds = HUBSPOT_CRED
    else:
        p.update({"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"})
        creds = EVABOOT_CRED
    node(name, "n8n-nodes-base.httpRequest", 4.2, p, pos, creds, **extra)


def iff(name, expr, pos):
    node(name, "n8n-nodes-base.if", 2.2, {"conditions": {
        "options": {"caseSensitive": True, "typeValidation": "loose", "version": 2},
        "combinator": "and", "conditions": [{"id": str(uuid.uuid4()), "leftValue": expr, "rightValue": "",
                                             "operator": {"type": "boolean", "operation": "true", "singleValue": True}}]},
        "options": {}}, pos)


SEARCH = ("={{ JSON.stringify({ limit: Number($json.limit) || 50, properties: " + json.dumps(PROPS) + ", "
          "filterGroups: ['email', 'jobtitle'].map(p => ({ filters: ["
          "{ propertyName: p, operator: 'NOT_HAS_PROPERTY' }, "
          "{ propertyName: 'ai_enrichment_status', operator: 'NOT_HAS_PROPERTY' }, "
          "{ propertyName: 'createdate', operator: 'GTE', value: String(Date.now() - Number($json.since_days || 7) * 86400000) }]})) }) }}")

CONTACTS_JS = r"""
// One item per HubSpot contact; sn_id is the Sales Navigator id Evaboot needs (a public /in/ name is not one).
const results = ($json.body && $json.body.results) || [];
return results.map(r => {
  const p = r.properties || {};
  const li = p.hs_linkedin_url || '';
  const m = li.match(/(?:\/sales\/lead\/|\/in\/)(ACw[\w-]+)/) || li.match(/\/sales\/lead\/([^,\/?]+)/);
  return { json: { id: r.id, crm: p, sn_id: m ? m[1] : '', steps: [] } };
});
"""

FINDER_BODY = ("={{ JSON.stringify(Object.assign({ first_name: $json.crm.firstname, last_name: $json.crm.lastname }, "
               "$json.crm.company ? { company_name: $json.crm.company } : {}, "
               "$json.crm.website ? { company_domain: $json.crm.website.replace(/^https?:\\/\\/(www\\.)?/, '').split('/')[0] } : {})) }}")

CHECK_JS = r"""
// Same rules as enrich.py updates(): fill only empty fields; a safe email on the company's domain only.
const SENIORITY = new Set(['owner', 'partner', 'executive', 'vp', 'director', 'manager', 'senior', 'entry', 'employee']);
const contacts = Object.fromEntries($('All contacts').all().map(it => [it.json.id, it.json]));
const dom = v => String(v || '').trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').split('/')[0];
const today = new Date(); today.setUTCHours(0, 0, 0, 0);
const out = [];
for (const item of $input.all()) {
  for (const v of (item.json.output && item.json.output.contacts) || []) {
    const c = contacts[v.id];
    if (!c) continue;
    const crm = c.crm, f = c.found || {};
    const status = f.title ? 'enriched' : (f.email ? 'email_only' : 'not_found');
    const site = dom(crm.website) || dom(f.company_domain);
    const mail = String(f.email || '').toLowerCase().split('@')[1] || '';
    const held = site && mail && !(mail === site || mail.endsWith('.' + site)) ? `${f.email} is not on ${site}` : '';
    const props = { ai_enrichment_status: status, ai_enriched_at: String(today.getTime()) };
    if (f.email && !crm.email && f.email_status === 'safe' && !held) props.email = f.email;
    if (f.title && !crm.jobtitle) props.jobtitle = f.title;
    if (f.linkedin && !crm.hs_linkedin_url) props.hs_linkedin_url = f.linkedin;
    if (f.company_domain && !crm.website) props.website = f.company_domain;
    if (v.job_function && f.title && !crm.job_function) props.job_function = v.job_function;
    if (SENIORITY.has(v.seniority) && f.title && !crm.hs_seniority) props.hs_seniority = v.seniority;
    const summary = String(v.summary || '').split(/\s+/).slice(0, 30).join(' ');
    props.ai_enrichment_summary = `[${['good', 'maybe', 'no'].includes(v.fit) ? v.fit : 'maybe'}] ${summary}` + (held ? ` Email held: ${held}` : '');
    out.push({ json: { id: c.id, properties: props } });
  }
}
return out;
"""

JUDGE_SYSTEM = """You review contacts that an enrichment step just completed. For each contact in the JSON (CRM fields plus what Evaboot found: title, company size, industry, growth, months in role, email status), return a job function, a seniority and a fit against the buyers below, and one summary line. Use only these facts; never invent anything.

Return {contacts: [{id, job_function, seniority, fit, summary}]}:
- job_function: a short department name (Sales, Marketing, Engineering...), only when a title is known, else "".
- seniority: one of owner, partner, executive, vp, director, manager, senior, entry, employee, only when a title is known, else "".
- fit: good, maybe or no. A row whose name is not a person (a team or company page) is no.
- summary: one line under 30 words on who they are and why they fit or not. When no title was found, say so.
- Never guess anyone's gender: no he, she, him or her. Use the first name, \"they\" or the role.

Buyers:
{{ $('Settings').first().json.buyers }}"""

node("Every morning at 7", "n8n-nodes-base.scheduleTrigger", 1.2, {"rule": {"interval": [
    {"field": "cronExpression", "expression": "0 7 * * *"}]}}, [0, 0])
node("Settings", "n8n-nodes-base.set", 3.4, {"assignments": {"assignments": [
    {"id": str(uuid.uuid4()), "name": k, "type": "string", "value": v} for k, v in [
        ("since_days", "7"), ("limit", "50"),
        ("buyers", "Heads of Sales, Sales Ops, RevOps, SDR managers and founders at B2B software companies of "
                   "51 to 500 employees with a sales team of 5 or more. Not a fit: engineering, design, "
                   "support and finance roles.")]]},
    "includeOtherFields": False, "options": {}}, [200, 0])
http("Contacts to enrich", "POST", "https://api.hubapi.com/crm/v3/objects/contacts/search", SEARCH, [400, 0], "hubspot")
code("One item per contact", CONTACTS_JS, [600, 0])
iff("Has a Sales Navigator id", "={{ !!$json.sn_id }}", [800, 0])
http("Evaboot profile export", "POST", "https://api.evaboot.com/v1/extractions/single/",
     "={{ JSON.stringify({ profile_id: $json.crm.hs_linkedin_url }) }}", [1000, -180], "evaboot")
code("Read the profile", r"""
// Read the profile export into `found`, keeping the contact it belongs to.
const contacts = $('Has a Sales Navigator id').all(0, 0);
const num = v => { const n = parseFloat(String(v ?? '').replace(/[,%]/g, '')); return isNaN(n) ? null : n; };
return $input.all().map((item, i) => {
  const c = contacts[i].json;
  const body = item.json.body || {};
  const p = body.prospect || null;
  const found = p ? { email: p['Email'] || '', email_status: String(p['Email Status'] || '').toLowerCase(),
    title: String(p['Current Job'] || '').trim(), company_domain: p['Company Domain'] || '',
    employees: p['Company Employee Range'] || '', industry: p['Company Industry'] || '',
    growth_1y_pct: num(p['Company Employee Growth 1 Year (%)']), linkedin: p['Linkedin URL Public'] || '',
    months_in_role: (num(p['Years in Position']) || 0) * 12 + (num(p['Months in Position']) || 0) } : {};
  const step = p ? 'profile: ok' : 'profile: ' + ((body.error && body.error.message) || 'HTTP ' + item.json.statusCode);
  return { json: { ...c, found, steps: [...c.steps, step] } };
});
""", [1200, -180])
iff("Still needs an email", "={{ !$json.found.email }}", [1400, -180])
node("Needs the finder", "n8n-nodes-base.merge", 3.2, {}, [1000, 180])
http("Evaboot email finder", "POST", "https://api.evaboot.com/v1/email-finder/single/", FINDER_BODY, [1200, 180], "evaboot")
code("Read the email", r"""
// The finder answer, back on the contact it was asked for (same order as its input).
const sent = $('Needs the finder').all();
return $input.all().map((item, i) => {
  const c = { ...sent[i].json, found: sent[i].json.found || {}, steps: sent[i].json.steps || [] };
  const p = (item.json.body && item.json.body.prospect) || {};
  const ok = !!p.found_email;
  const found = ok ? { ...c.found, email: p.found_email, email_status: String(p.email_validity || '').toLowerCase(),
    company_domain: c.found.company_domain || p.company_domain || '' } : c.found;
  return { json: { ...c, found, steps: [...c.steps, 'email finder: ' + (ok ? 'ok' : (p.error_message || 'no email found'))] } };
});
""", [1400, 180])
node("All contacts", "n8n-nodes-base.merge", 3.2, {}, [1620, 0])
node("Judge with Claude", "@n8n/n8n-nodes-langchain.agent", 2.2, {
    "promptType": "define", "hasOutputParser": True,
    "text": "={{ JSON.stringify($input.all().map(i => ({ id: i.json.id, name: (i.json.crm.firstname + ' ' + i.json.crm.lastname).trim(), "
            "company: i.json.crm.company, crm_title: i.json.crm.jobtitle, title: i.json.found.title || '', "
            "employees: i.json.found.employees || '', industry: i.json.found.industry || '', "
            "growth_1y_pct: i.json.found.growth_1y_pct, months_in_role: i.json.found.months_in_role, "
            "email_status: i.json.found.email_status || 'not found' }))) }}",
    "options": {"systemMessage": "=" + JUDGE_SYSTEM, "maxIterations": 3},
}, [1820, 0], executeOnce=True, retryOnFail=True, maxTries=3, waitBetweenTries=2000)
node("Claude", "@n8n/n8n-nodes-langchain.lmChatAnthropic", 1.3, {
    "model": {"__rl": True, "mode": "list", "value": MODEL, "cachedResultName": MODEL},
    "options": {"maxTokensToSample": 4000},
}, [1780, 220], ANTHROPIC_CRED)
node("Contact verdicts", "@n8n/n8n-nodes-langchain.outputParserStructured", 1.3, {
    "schemaType": "manual",
    "inputSchema": json.dumps({"type": "object", "required": ["contacts"], "properties": {"contacts": {
        "type": "array", "items": {"type": "object", "required": ["id", "fit", "summary"], "properties": {
            "id": {"type": "string"}, "job_function": {"type": "string"}, "seniority": {"type": "string"},
            "fit": {"type": "string"}, "summary": {"type": "string"}}}}}}, indent=2),
}, [1940, 220])
code("Check and build the update", CHECK_JS, [2160, 0])
http("Update the contact", "PATCH", "=https://api.hubapi.com/crm/v3/objects/contacts/{{ $json.id }}",
     "={{ JSON.stringify({ properties: $json.properties }) }}", [2360, 0], "hubspot")

for a, b, o, i in [("Every morning at 7", "Settings", 0, 0), ("Settings", "Contacts to enrich", 0, 0),
                   ("Contacts to enrich", "One item per contact", 0, 0), ("One item per contact", "Has a Sales Navigator id", 0, 0),
                   ("Has a Sales Navigator id", "Evaboot profile export", 0, 0), ("Has a Sales Navigator id", "Needs the finder", 1, 1),
                   ("Evaboot profile export", "Read the profile", 0, 0), ("Read the profile", "Still needs an email", 0, 0),
                   ("Still needs an email", "Needs the finder", 0, 0), ("Still needs an email", "All contacts", 1, 0),
                   ("Needs the finder", "Evaboot email finder", 0, 0), ("Evaboot email finder", "Read the email", 0, 0),
                   ("Read the email", "All contacts", 0, 1), ("All contacts", "Judge with Claude", 0, 0),
                   ("Judge with Claude", "Check and build the update", 0, 0),
                   ("Check and build the update", "Update the contact", 0, 0)]:
    connections.setdefault(a, {}).setdefault("main", [])
    while len(connections[a]["main"]) <= o:
        connections[a]["main"].append([])
    connections[a]["main"][o].append({"node": b, "type": "main", "index": i})
link("Claude", "Judge with Claude", "ai_languageModel")
link("Contact verdicts", "Judge with Claude", "ai_outputParser")

workflow = {"name": "AI lead enrichment (Evaboot + Claude + HubSpot)", "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1"}, "pinData": {}}
out = Path(__file__).with_name("ai-lead-enrichment.json")
out.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n")
print(out, len(nodes), "nodes")
