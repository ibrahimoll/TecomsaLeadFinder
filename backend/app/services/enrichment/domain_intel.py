"""Passive domain intelligence: what a company's PUBLIC DNS records and registration data say about its technology.

    MX                  e-mail provider (Microsoft 365, Google Workspace, Zoho Mail, self-hosted...)
    TXT (SPF)           services allowed to send its e-mail (Mailchimp, SendGrid, Amazon SES...)
    TXT _dmarc          whether it publishes a DMARC policy (and which)
    NS                  DNS hosting (Cloudflare, AWS Route 53, GoDaddy...)
    RDAP                domain registration date (gTLDs; .lb has no RDAP service)

Read through public DNS-over-HTTPS and RDAP: the same answers any mail server or browser gets. No probing, no port or
vulnerability scanning, no zone transfers, nothing beyond a handful of lookups per domain. Stored as company signals
with their evidence (one Source per domain); refreshed after FRESH_DAYS.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Company, CompanySignal, Source
from app.services.enrichment import persistence
from app.services.enrichment.extract import Fact

logger = logging.getLogger("leadfinder.enrichment.domain")
DOH = "https://cloudflare-dns.com/dns-query"
RDAP = "https://rdap.org/domain/"
FRESH_DAYS = 30
QUALITY = 90
MX_PROVIDERS = (("outlook.com", "Microsoft 365"), ("protection.outlook", "Microsoft 365"),
                ("google.com", "Google Workspace"), ("googlemail.com", "Google Workspace"), ("zoho", "Zoho Mail"),
                ("mimecast", "Mimecast"), ("pphosted.com", "Proofpoint"), ("barracudanetworks", "Barracuda"),
                ("secureserver.net", "GoDaddy e-mail"), ("ovh.net", "OVH e-mail"), ("yandex", "Yandex Mail"),
                ("icloud.com", "iCloud Mail"), ("messagingengine.com", "Fastmail"), ("titan.email", "Titan Mail"),
                ("hostinger", "Hostinger e-mail"), ("emailsrvr.com", "Rackspace e-mail"))
SPF_SERVICES = (("spf.protection.outlook.com", "Microsoft 365"), ("_spf.google.com", "Google Workspace"),
                ("servers.mcsv.net", "Mailchimp"), ("sendgrid.net", "SendGrid"), ("amazonses.com", "Amazon SES"),
                ("zoho", "Zoho"), ("mailgun.org", "Mailgun"), ("spf.mandrillapp.com", "Mandrill"),
                ("_spf.salesforce.com", "Salesforce"), ("hubspotemail.net", "HubSpot"), ("zendesk.com", "Zendesk"),
                ("brevo", "Brevo"), ("sendinblue", "Brevo"), ("freshdesk", "Freshdesk"), ("odoo", "Odoo"))
NS_PROVIDERS = (("cloudflare.com", "Cloudflare"), ("awsdns", "AWS Route 53"), ("domaincontrol.com", "GoDaddy"),
                ("azure-dns", "Azure DNS"), ("googledomains.com", "Google Domains"), ("google.com", "Google Cloud DNS"),
                ("hostinger", "Hostinger"), ("namecheaphosting", "Namecheap"), ("registrar-servers.com", "Namecheap"),
                ("wixdns.net", "Wix"), ("ovh.net", "OVH"), ("digitalocean.com", "DigitalOcean"),
                ("nsone.net", "NS1"), ("dnsmadeeasy", "DNS Made Easy"), ("hetzner", "Hetzner"))


def _lookup(http, name: str, rtype: str) -> list[str]:
    r = http.get(DOH, params={"name": name, "type": rtype}, headers={"Accept": "application/dns-json"})
    if r.status_code != 200:
        return []
    return [a.get("data", "").strip('"').lower() for a in r.json().get("Answer") or [] if a.get("data")]


def _first(table, values: list[str]) -> str | None:
    return next((label for key, label in table for v in values if key in v), None)


def records(http, domain: str) -> dict:
    """What the public DNS says (lower-cased answers), and the registration date when RDAP knows it."""
    mx = [v.split()[-1].rstrip(".") for v in _lookup(http, domain, "MX")]
    txt = _lookup(http, domain, "TXT")
    spf = next((v for v in txt if v.startswith("v=spf1")), None)
    dmarc = next((v for v in _lookup(http, f"_dmarc.{domain}", "TXT") if v.startswith("v=dmarc1")), None)
    ns = [v.rstrip(".") for v in _lookup(http, domain, "NS")]
    registered = None
    if not domain.endswith(".lb"):
        r = http.get(RDAP + domain, headers={"Accept": "application/rdap+json"})
        if r.status_code == 200:
            registered = next((e.get("eventDate") for e in r.json().get("events") or []
                               if e.get("eventAction") == "registration"), None)
    return {"mx": mx, "spf": spf, "dmarc": dmarc, "ns": ns, "registered": registered}


def classify(rec: dict, domain: str) -> list[tuple[str, str, str]]:
    """(signal type, value, why) from the records."""
    out = []
    if provider := _first(MX_PROVIDERS, rec["mx"]):
        out.append(("email_provider", provider, f"MX: {', '.join(rec['mx'][:3])}"))
    elif rec["mx"]:
        own = any(h.endswith(domain) for h in rec["mx"])
        out.append(("email_provider", "Self-hosted e-mail" if own else "Other e-mail host",
                    f"MX: {', '.join(rec['mx'][:3])}"))
    for key, label in SPF_SERVICES:
        if rec["spf"] and key in rec["spf"]:
            out.append(("email_sending_service", label, f"SPF: {rec['spf'][:200]}"))
    if rec["dmarc"]:
        policy = next((p.split("=")[1] for p in rec["dmarc"].replace(" ", "").split(";") if p.startswith("p=")), "none")
        out.append(("email_security", f"DMARC p={policy}", f"_dmarc: {rec['dmarc'][:200]}"))
    elif rec["mx"]:
        out.append(("email_security", "No DMARC policy", "no _dmarc record"))
    if provider := _first(NS_PROVIDERS, rec["ns"]):
        out.append(("dns_provider", provider, f"NS: {', '.join(rec['ns'][:3])}"))
    return list(dict.fromkeys(out))


def is_fresh(db: Session, company: Company) -> bool:
    last = db.scalar(select(func.max(CompanySignal.observed_at)).where(
        CompanySignal.company_id == company.id, CompanySignal.signal_type.in_(
            ("email_provider", "dns_provider", "email_security"))))
    return bool(last and datetime.now(timezone.utc) - last < timedelta(days=FRESH_DAYS))


def foreign_brand(company: Company) -> bool:
    """The website is a global brand's (a store page on nike.com; a domain whose Wikidata item is a foreign
    organisation): its DNS describes the brand, not this company."""
    from app.services.people.orchestrator import brand_page

    return brand_page(company.website) or bool((company.people_coverage or {}).get("foreign_brand_domain"))


def run(db: Session, company: Company, http, *, force: bool = False) -> int:
    if not company.domain or foreign_brand(company) or (not force and is_fresh(db, company)):
        return 0
    rec = records(http, company.domain)
    now = datetime.now(timezone.utc)
    url = f"dns://{company.domain}"
    source = db.scalar(select(Source).where(Source.url == url).limit(1))
    if source is None:
        source = Source(source_type="public_web", name=f"Public DNS records of {company.domain}", url=url,
                        publisher="DNS / RDAP", retrieved_at=now, source_quality=QUALITY,
                        metadata_={"connector": "dns"})
        db.add(source)
        db.flush()
    source.retrieved_at = now
    found = classify(rec, company.domain)
    facts = [Fact("signal", kind, value, QUALITY, why) for kind, value, why in found]
    if facts:
        persistence.save_facts(db, company, source, facts, now, company.headquarters_country or "Lebanon")
    if rec["registered"]:
        when = datetime.fromisoformat(rec["registered"].replace("Z", "+00:00"))
        stmt = insert(CompanySignal).values(
            company_id=company.id, signal_type="domain_registered", signal_value=company.domain, confidence=QUALITY,
            source_id=source.id, observed_at=now, event_date=when.date(),
            description=f"Website domain {company.domain} registered")
        db.execute(stmt.on_conflict_do_nothing())
    db.commit()
    return len(facts)
