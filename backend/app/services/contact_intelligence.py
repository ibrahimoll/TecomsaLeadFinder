"""Contact intelligence (Step 6): how to reach the people LeadFinder found, with the strength of each channel stated.

    published   an address / number the person's own entry or the company's own pages publish for that person
                (an address counts as the person's only when it spells their full name: joseph.haddad@,
                jhaddad@ is a pattern sample, not proof); generic mailboxes (info@, sales@) stay the company's
    pattern     how the company forms addresses (first.last, flast...), observed on real published addresses of
                its people at its own domain: the evidence for a prediction, never an address
    predicted   at most 5 candidates for a decision-maker without a published address: the observed pattern first,
                else a small conservative set; stored as PREDICTED (one per person), never shown as verified
    verified    EmailVerifier, provider-neutral: syntax, domain, MX (no mail setup: INVALID); with
                EMAIL_SMTP_VERIFICATION a mailbox check (RCPT, never DATA: nothing is sent): the server accepts any
                address (catch-all): CATCH_ALL; accepts this one only: VERIFIED; refuses it: INVALID; can't tell:
                UNKNOWN. Off by default (a mailbox check talks to the company's mail server)
    phones      published numbers classified: business mobile (Lebanese mobile ranges), office extension, the
                company's switchboard (never presented as the person's direct line), direct business phone,
                WhatsApp only where the source says so. No number is ever inferred.

Human-confirmed and internal-CRM contact points are never overwritten. One job per company (research_runs
'contact_discovery'), bounded (CONTACT_JOB_SECONDS), ending completed / partial / timed_out.
"""

import logging
import random
import re
import smtplib
import string
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (Company, CompanyEmailPattern, CompanyPerson, CompanyWebPage, ContactEvidence, Email,
                        ExternalDocument, Person, Phone, ResearchRun)
from app.models.enums import EmailStatus, EnrichmentStatus, ResearchRunStatus

logger = logging.getLogger("leadfinder.contacts")
EMAIL = re.compile(r"[a-z0-9][a-z0-9._%+-]{0,63}@[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE)
ROLE_MAILBOXES = {"info", "sales", "support", "contact", "hello", "admin", "office", "hr", "jobs", "careers",
                  "marketing", "accounts", "accounting", "finance", "billing", "orders", "service", "services",
                  "enquiries", "inquiries", "reception", "mail", "webmaster", "noreply", "no-reply", "press",
                  "media", "team", "it", "procurement", "purchasing", "export", "import", "management", "ceo",
                  "gm", "director", "secretary", "booking", "reservations", "events", "admissions", "registrar"}
PATTERNS = {  # name -> local part of first / last name
    "first.last": lambda f, l: f"{f}.{l}", "flast": lambda f, l: f"{f[0]}{l}", "first": lambda f, l: f,
    "firstlast": lambda f, l: f"{f}{l}", "first_last": lambda f, l: f"{f}_{l}", "f.last": lambda f, l: f"{f[0]}.{l}",
    "last.first": lambda f, l: f"{l}.{f}", "firstl": lambda f, l: f"{f}{l[0]}", "first-last": lambda f, l: f"{f}-{l}",
    "lastf": lambda f, l: f"{l}{f[0]}", "last": lambda f, l: l}
FULL_NAME_PATTERNS = ("first.last", "firstlast", "first_last", "first-last", "last.first")  # spell the whole name
CONSERVATIVE = ("first.last", "flast", "first", "firstlast")  # no observed pattern: the common ones only
MAX_CANDIDATES = 5
LEBANON_MOBILE = re.compile(r"^(?:3\d{6}|7[0-9]\d{6}|81\d{6})$")
FREE_MAIL = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "live.com", "icloud.com", "aol.com",
             "msn.com", "proton.me", "protonmail.com"}
CONTACT_FRESH_DAYS = 14
# relevant decision-makers: the departments TECOMSA sells to, manager level and above
DM_DEPARTMENTS = ("executive", "it", "finance", "operations", "procurement", "supply_chain", "manufacturing",
                  "sales", "marketing", "hr", "customer_experience", "e_commerce")
DM_SENIORITY = ("owner", "c_level", "vp", "director", "head", "manager")


# ---- names and patterns -------------------------------------------------------------------------------------------


def name_parts(full_name: str) -> tuple[str, str] | None:
    """(first, last) in plain lowercase Latin letters, or None (a one-word or non-Latin name: no pattern)."""
    text_ = unicodedata.normalize("NFKD", full_name)
    text_ = "".join(ch for ch in text_ if not unicodedata.combining(ch)).lower()
    words = [re.sub(r"[^a-z]", "", w) for w in re.split(r"[\s\-]+", text_)]
    words = [w for w in words if w and w not in ("dr", "mr", "mrs", "ms", "eng", "prof", "sir", "el", "al")]
    if len(words) < 2 or any(not w.isascii() for w in words):
        return None
    return words[0], words[-1]


def pattern_of(local: str, first: str, last: str) -> str | None:
    local = local.lower()
    return next((name for name, make in PATTERNS.items() if make(first, last) == local), None)


def candidates(first: str, last: str, domain: str, patterns: list[str]) -> list[tuple[str, str]]:
    """(address, pattern): the observed patterns first, else the conservative set; never more than 5."""
    order = list(dict.fromkeys([*patterns, *([] if patterns else CONSERVATIVE)]))
    return [(f"{PATTERNS[p](first, last)}@{domain}", p) for p in order if p in PATTERNS][:MAX_CANDIDATES]


# ---- phones ---------------------------------------------------------------------------------------------------------


def national(number: str | None) -> str | None:
    from app.services.people.external.lebanon.identity import phone_key

    return phone_key(number)


def classify_phone(raw: str, *, company_numbers: set[str], context: str = "") -> str:
    """The kind of a published number of a person. A company number is its switchboard, not the person's line."""
    key = national(raw)
    folded = context.lower()
    if key and key in company_numbers:
        return "company_switchboard"
    if re.search(r"whats\s?app", folded):
        return "whatsapp"
    if re.search(r"\b(?:ext|extension|poste)\.?\s*\d", f"{raw} {folded}", re.IGNORECASE):
        return "office_extension"
    if key and LEBANON_MOBILE.match(key):
        return "business_mobile"
    return "direct_business_phone"


# ---- email verification -------------------------------------------------------------------------------------------


@dataclass
class EmailCheck:
    status: str  # verified / invalid / catch_all / unknown (a predicted address stays predicted when unknown)
    details: dict = field(default_factory=dict)


class EmailVerifier(Protocol):
    key: str

    def check(self, addresses: list[str]) -> dict[str, EmailCheck]: ...


_MX_CACHE: dict[str, tuple[float, list[str]]] = {}


def mx_hosts(domain: str) -> list[str] | None:
    """The domain's mail servers (priority order); [] when the domain receives no mail; None when DNS failed."""
    import dns.exception
    import dns.resolver

    cached = _MX_CACHE.get(domain)
    if cached and time.monotonic() - cached[0] < 3600:
        return cached[1]
    resolver = dns.resolver.Resolver()
    resolver.lifetime = resolver.timeout = 4
    try:
        answers = sorted(resolver.resolve(domain, "MX"), key=lambda r: r.preference)
        hosts = [str(r.exchange).rstrip(".") for r in answers if str(r.exchange).rstrip(".")]  # '.' = null MX
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        try:  # no MX: the domain's own address receives mail (RFC 5321)
            resolver.resolve(domain, "A")
            hosts = [domain]
        except Exception:
            hosts = []
    except dns.exception.DNSException:
        return None
    _MX_CACHE[domain] = (time.monotonic(), hosts)
    return hosts


class DnsEmailVerifier:
    """Syntax, domain and mail setup only: a mailbox it cannot see stays UNKNOWN (never VERIFIED)."""

    key = "dns"

    def check(self, addresses: list[str]) -> dict[str, EmailCheck]:
        out = {}
        for address in addresses:
            if not EMAIL.fullmatch(address or ""):
                out[address] = EmailCheck("invalid", {"syntax": False})
                continue
            domain = address.split("@")[1].lower()
            hosts = mx_hosts(domain)
            if hosts == []:
                out[address] = EmailCheck("invalid", {"syntax": True, "mx": []})
            else:
                out[address] = EmailCheck("unknown", {"syntax": True, "mx": (hosts or [])[:3],
                                                      "dns_error": hosts is None})
        return out


class SmtpEmailVerifier(DnsEmailVerifier):
    """+ a mailbox check at the company's mail server: RCPT only (the session is closed before DATA, nothing is
    sent), one connection per domain, a random address first (accepted: catch-all, nothing can be verified)."""

    key = "smtp"

    def check(self, addresses: list[str]) -> dict[str, EmailCheck]:
        out = super().check(addresses)
        by_domain: dict[str, list[str]] = {}
        for address, result in out.items():
            if result.status == "unknown" and result.details.get("mx"):
                by_domain.setdefault(address.split("@")[1].lower(), []).append(address)
        for domain, items in by_domain.items():
            if domain in FREE_MAIL:
                continue  # a personal mailbox provider: never probed
            host = out[items[0]].details["mx"][0]
            try:
                results = self._probe(host, domain, items)
            except (OSError, smtplib.SMTPException) as exc:
                for a in items:
                    out[a].details["smtp"] = f"unavailable ({exc.__class__.__name__})"
                continue
            for a in items:
                out[a] = EmailCheck(results[a], {**out[a].details, "smtp": results[a], "host": host})
        return out

    @staticmethod
    def _probe(host: str, domain: str, addresses: list[str]) -> dict[str, str]:
        timeout = get_settings().email_smtp_timeout_seconds
        with smtplib.SMTP(host, 25, timeout=timeout, local_hostname=get_settings().email_smtp_helo) as smtp:
            smtp.ehlo_or_helo_if_needed()
            if smtp.mail(get_settings().email_smtp_mail_from)[0] >= 400:  # closed before DATA: never a message
                raise smtplib.SMTPException("sender refused")
            probe = "".join(random.choices(string.ascii_lowercase, k=14)) + "@" + domain
            probe_code, probe_text = smtp.rcpt(probe)
            if probe_code >= 500 and not _no_such_user(probe_code, probe_text):
                raise smtplib.SMTPException("recipient checks refused (policy)")  # blocked: nothing can be told
            catch_all = probe_code < 300
            results = {}
            for address in addresses:
                code, reply = smtp.rcpt(address)
                results[address] = ("catch_all" if catch_all and code < 300 else "verified" if code < 300
                                    else "invalid" if _no_such_user(code, reply) else "unknown")
            smtp.rset()
        return results


def _no_such_user(code: int, reply: bytes | str) -> bool:
    """Only an explicit 'this mailbox does not exist' (5.1.x / user unknown) proves an address invalid; a policy
    refusal (5.7.x: this host is blocked, rate limited...) proves nothing."""
    text_ = reply.decode("latin-1", "replace") if isinstance(reply, bytes) else str(reply)
    return code in (550, 551, 553) and bool(re.search(
        r"\b5\.1\.[0-9]\b|(?:user|recipient) unknown|unknown (?:user|recipient)|no such user|does not exist|mailbox unavailable|"
        r"recipient (?:address )?rejected|invalid recipient|not found", text_, re.IGNORECASE)) and not re.search(
        r"\b5\.7\.[0-9]\b|blocked|spamhaus|policy|blacklist|denied|reputation", text_, re.IGNORECASE)


def verifier() -> EmailVerifier:
    return SmtpEmailVerifier() if get_settings().email_smtp_verification else DnsEmailVerifier()


# ---- ranking (what the People tab shows first) ----------------------------------------------------------------------

# The order a lead generator sees (Step 6.2 result priority): confirmed, published, TECOMSA CRM, delivered,
# high-confidence predicted, predicted. A phone of the person ranks with the published contacts.
RANK = ("confirmed_email", "verified_email", "corroborated_email", "published_email", "business_mobile", "direct_business_phone",
        "whatsapp", "office_extension", "internal_email", "business_phone", "delivered_email", "high_confidence_email",
        "catch_all_email", "predicted_email")
LABEL = {"confirmed_email": "Confirmed (reply received)", "verified_email": "Verified", "published_email": "Published",
         "business_mobile": "Published business mobile",
         "direct_business_phone": "Published direct line", "whatsapp": "Published WhatsApp",
         "office_extension": "Office extension", "catch_all_email": "Unconfirmed (domain accepts any address)",
         "predicted_email": "Predicted", "company_switchboard": "Company switchboard",
         "company_email": "Company email", "human_confirmed": "Confirmed by a colleague",
         "business_phone": "Phone (type not confirmed)", "internal_email": "TECOMSA CRM",
         "delivered_email": "Delivered (no reply yet)", "high_confidence_email": "Predicted (high confidence)",
         "corroborated_email": "Corroborated (2+ sources)", "contributed": "Contributed business contact"}
USABLE = set(RANK[:9])  # directly contactable; delivered / predicted addresses and untyped phones are not
STALE_DAYS = 730  # a contact last confirmed / seen longer ago is shown as possibly outdated (never deleted)


def channels(emails, phones, corroborated: frozenset = frozenset()) -> list[dict]:
    """A person's contact methods, strongest first (a predicted address never above a published channel), each with
    when it was last confirmed (else last seen) and whether that is old."""
    out = []
    now = datetime.now(timezone.utc)

    def label(kind: str, provenance: str) -> str:
        if kind in ("confirmed_email", "corroborated_email"):
            return LABEL[kind]
        if provenance == "internal_crm":
            return "TECOMSA CRM"
        if provenance == "contributed":
            return LABEL["contributed"]
        if provenance == "licensed":
            return "Licensed directory"
        if provenance == "lusha":
            return "Lusha"
        return LABEL["human_confirmed" if provenance == "human_confirmed" else kind]

    def entry(kind: str, value: str, row) -> dict:
        when = row.last_verified_at or row.last_seen_at or row.first_seen_at
        return {"kind": kind, "value": value, "label": label(kind, row.provenance),
                "since": when.date().isoformat() if when else None,
                "stale": bool(when and (now - when).days > STALE_DAYS)}

    for e in emails:
        if e.status in ("invalid",):
            continue
        kind = {"verified": "verified_email", "published": "published_email", "discovered": "published_email",
                "catch_all": "catch_all_email", "predicted": "predicted_email", "confirmed": "confirmed_email",
                "high_confidence_predicted": "high_confidence_email"}.get(e.status)
        if kind == "published_email" and e.provenance == "internal_crm":
            kind = "internal_email"
        if kind in ("published_email", "internal_email") and ("email", e.id) in corroborated:
            kind = "corroborated_email"  # two or more independent sources state it
        if kind in ("predicted_email", "high_confidence_email") and (e.verification or {}).get("delivered"):
            kind = "delivered_email"  # a real outreach reached it: stronger than a guess, not yet confirmed
        if kind:
            out.append(entry(kind, e.email, e))
    for p in phones:
        kind = {"business_mobile": "business_mobile", "mobile": "business_mobile", "whatsapp": "whatsapp",
                "office_extension": "office_extension", "extension": "office_extension",
                "unknown_business": "business_phone"}.get(p.phone_type or "", "direct_business_phone")
        if p.phone_type == "company_switchboard" or p.status == "invalid":
            continue  # a wrong number (sales feedback) / the company's number: the company fallback, never the person's
        row = entry(kind, p.phone, p)
        if ("phone", p.id) in corroborated:
            row["label"] = f"{row['label']} · corroborated"
        out.append(row)
    return sorted(out, key=lambda c: RANK.index(c["kind"]))


# ---- queueing -------------------------------------------------------------------------------------------------------


def is_due(db: Session, company: Company) -> bool:
    """Contact research is useful when the company has credible people and nothing new was tried since they were
    found (or it is older than CONTACT_FRESH_DAYS)."""
    people_at = db.scalar(select(func.max(CompanyPerson.updated_at)).where(
        CompanyPerson.company_id == company.id, CompanyPerson.confidence >= 50))
    if people_at is None:
        return False
    last = company.contact_researched_at
    return last is None or people_at > last or datetime.now(timezone.utc) - last > timedelta(days=CONTACT_FRESH_DAYS)


def request(db: Session, company: Company, priority: int, *, force: bool = False, user_id: int | None = None) -> bool:
    from app.services import jobs

    running = company.contact_status in (EnrichmentStatus.QUEUED, EnrichmentStatus.RESEARCHING)
    if running or not (force or is_due(db, company)):
        return False
    stmt = insert(ResearchRun).values(company_id=company.id, research_type=jobs.CONTACT,
                                      status=ResearchRunStatus.QUEUED.value, priority=priority,
                                      requested_by_user_id=user_id, metadata_={"force": force, **jobs.chained()})
    db.execute(stmt.on_conflict_do_update(index_elements=["company_id", "research_type"],
                                          index_where=text(jobs.ACTIVE),
                                          set_={"priority": func.least(ResearchRun.priority, priority)}))
    jobs.wake(db, jobs.CONTACT)
    company.contact_status = EnrichmentStatus.QUEUED.value
    return True


# ---- one company ----------------------------------------------------------------------------------------------------


def _published_addresses(db: Session, company: Company, domain: str) -> list[tuple[str, int | None, str]]:
    """(address, source_id, where) of every address at the company's domain its own pages and the corpus publish."""
    found: dict[str, tuple[str, int | None, str]] = {}
    for row in db.scalars(select(CompanyWebPage).where(CompanyWebPage.company_id == company.id,
                                                       CompanyWebPage.content.is_not(None))):
        content = row.content or {}
        texts = [b[1] for b in content.get("blocks") or [] if len(b) > 1] + \
            [link[0] for link in content.get("links") or [] if link and str(link[0]).startswith("mailto:")]
        for t in texts:
            for m in EMAIL.findall(t or ""):
                if m.lower().endswith("@" + domain):
                    found.setdefault(m.lower(), (m.lower(), row.source_id, row.url))
    for row in db.scalars(select(ExternalDocument).where(ExternalDocument.search_vector.op("@@")(
            func.plainto_tsquery("simple", domain.split(".")[0]))).limit(30)):
        blob = str(row.content or "")[:500_000]
        for m in EMAIL.findall(blob):
            if m.lower().endswith("@" + domain):
                found.setdefault(m.lower(), (m.lower(), row.source_id, row.url))
    # stored addresses count only when a source published them: a prediction must never re-enter as evidence
    for e in db.scalars(select(Email).where(Email.company_id == company.id, Email.email.like(f"%@{domain}"),
                                            Email.provenance != "predicted",
                                            Email.status.in_(("published", "discovered", "verified", "confirmed")))):
        found.setdefault(e.email, (e.email, e.source_id, "stored"))
    return list(found.values())


def _people(db: Session, company: Company) -> list[tuple[CompanyPerson, Person]]:
    return db.execute(select(CompanyPerson, Person).join(Person, Person.id == CompanyPerson.person_id).where(
        CompanyPerson.company_id == company.id, CompanyPerson.confidence >= 50,
        CompanyPerson.employment_status != "former")).all()


def _locked(db: Session, person_id: int, model) -> bool:
    """A person / company confirmed or internal contact point: research leaves that person's channel alone."""
    return bool(db.scalar(select(model.id).where(model.person_id == person_id,
                                                 model.provenance.in_(("human_confirmed", "internal_crm"))).limit(1)))


def run(db: Session, company_id: int, *, force: bool = False, queue_wait: float | None = None) -> dict:
    started = time.perf_counter()
    deadline = time.monotonic() + get_settings().contact_job_seconds
    stats: dict = {"queue_wait": round(queue_wait, 2) if queue_wait is not None else None}
    company = db.get(Company, company_id)
    if company is None:
        return {"status": "skipped"}
    company.contact_status, company.contact_message = EnrichmentStatus.RESEARCHING.value, None
    db.commit()
    now = datetime.now(timezone.utc)
    people = _people(db, company)
    domain = company.domain if (company.website_confidence or 0) >= 50 or company.domain else None
    company_numbers = {k for p in db.scalars(select(Phone.phone).where(Phone.company_id == company.id,
                                                                        Phone.person_id.is_(None)))
                       if (k := national(p))} | ({k} if (k := national(company.primary_phone)) else set())
    # 1. phones the sources published for people: classified (a company number is the switchboard)
    for phone in db.scalars(select(Phone).where(Phone.person_id.in_([p.id for _, p in people] or [0]),
                                                Phone.provenance == "public")):
        kind = classify_phone(phone.phone, company_numbers=company_numbers, context=phone.evidence or "")
        if phone.phone_type != kind:
            phone.phone_type, stats["phones_classified"] = kind, stats.get("phones_classified", 0) + 1
    patterns: dict[str, list[str]] = {}
    if domain and domain not in FREE_MAIL:
        # 2. published addresses: the person's own (full name) attached; every name match is a pattern sample
        named = {pid: parts for pid, parts in ((p.id, name_parts(p.full_name)) for _, p in people) if parts}
        for address, source_id, where in _published_addresses(db, company, domain):
            local = address.split("@")[0]
            if re.sub(r"[^a-z]", "", local) in ROLE_MAILBOXES:
                continue  # info@ / sales@: the company's, never a person's
            for pid, (first, last) in named.items():
                pattern = pattern_of(local, first, last)
                if not pattern:
                    continue
                patterns.setdefault(pattern, []).append(address)
                if pattern in FULL_NAME_PATTERNS and not _locked(db, pid, Email):
                    _save_email(db, company, pid, address, EmailStatus.PUBLISHED, "public", source_id, 85, now,
                                f"published at {where[:200]}: the address spells the person's name ({pattern})")
                    stats["published_attached"] = stats.get("published_attached", 0) + 1
        # the patterns are what the published addresses show today: one no longer observed is dropped
        db.execute(delete(CompanyEmailPattern).where(CompanyEmailPattern.company_id == company.id,
                                                     CompanyEmailPattern.pattern.not_in(list(patterns) or [""])))
        for pattern, samples in patterns.items():
            stmt = insert(CompanyEmailPattern).values(
                company_id=company.id, domain=domain, pattern=pattern, sample_count=len(set(samples)),
                confidence=min(95, 60 + 10 * len(set(samples))), evidence=sorted(set(samples))[:10])
            db.execute(stmt.on_conflict_do_update(constraint="uq_company_email_patterns_company_domain_pattern",
                                                  set_={"sample_count": stmt.excluded.sample_count,
                                                        "confidence": stmt.excluded.confidence,
                                                        "evidence": stmt.excluded.evidence, "updated_at": now}))
        db.commit()
        ranked = [p for p, _ in sorted(patterns.items(), key=lambda kv: -len(set(kv[1])))]
        # 3. decision-makers without a published / verified address: bounded candidates, then verification
        # only a confirmed current decision-maker gets a predicted address; one no longer so loses it
        dms = [(role, person) for role, person in people if role.employment_status == "current"
               and role.department in DM_DEPARTMENTS and role.seniority in DM_SENIORITY]
        db.execute(delete(Email).where(Email.company_id == company.id, Email.provenance == "predicted",
                                       Email.person_id.not_in({p.id for _, p in dms} or {0})))
        wanted = []
        for role, person in dms:
            parts = name_parts(person.full_name)
            has = db.scalar(select(Email.id).where(Email.person_id == person.id, Email.status.in_(
                ("published", "discovered", "verified", "confirmed"))).limit(1))
            if parts and not has and not _locked(db, person.id, Email):
                wanted.append((person, candidates(*parts, domain, ranked[:2])))
        checker = verifier()
        stats["verifier"] = checker.key
        for person, options in wanted:
            if time.monotonic() > deadline:
                stats["stopped_deadline"] = True
                break
            results = checker.check([a for a, _ in options])
            chosen = next(((a, p) for a, p in options if results[a].status == "verified"), None)
            if chosen:
                status, provenance, confidence = EmailStatus.VERIFIED, "verified", 90
            elif all(results[a].status == "invalid" for a, _ in options):
                stats["all_candidates_invalid"] = stats.get("all_candidates_invalid", 0) + 1
                continue  # no mail setup / every candidate refused: nothing to show
            else:
                chosen = options[0]
                catch_all = results[chosen[0]].status == "catch_all"
                samples = len(set(patterns.get(chosen[1], [])))
                # >= 2 real published addresses of this pattern at the verified domain (whose MX answered):
                # a stronger guess, still never confirmed
                strong = not catch_all and samples >= 2 and chosen[1] == (ranked or [None])[0]
                status = EmailStatus.CATCH_ALL if catch_all else (
                    EmailStatus.HIGH_CONFIDENCE_PREDICTED if strong else EmailStatus.PREDICTED)
                provenance, confidence = "predicted", 75 if strong else 60 if ranked else 35
            basis = (f"observed company pattern {chosen[1]} ({len(set(patterns.get(chosen[1], [])))} published "
                     f"address(es))" if chosen[1] in patterns else f"common pattern {chosen[1]} (no observed pattern)")
            _save_email(db, company, person.id, chosen[0], status, provenance, None, confidence, now, basis,
                        results[chosen[0]].details)
            stats[f"email_{status.value}"] = stats.get(f"email_{status.value}", 0) + 1
        db.commit()
    elif domain in FREE_MAIL:
        stats["free_mail_domain"] = True
    status = EnrichmentStatus.TIMED_OUT if stats.get("stopped_deadline") else (
        EnrichmentStatus.COMPLETED if domain else EnrichmentStatus.PARTIAL)
    company.contact_status = status.value
    company.contact_message = None if domain else "No verified company domain: work emails cannot be predicted."
    company.contact_researched_at = datetime.now(timezone.utc)
    db.commit()
    stats.update(status=company.contact_status, patterns=sorted(patterns), people=len(people),
                 seconds=round(time.perf_counter() - started, 2))
    logger.info("company=%s contacts=%s %s", company.id, company.contact_status, stats)
    return stats


def _save_email(db: Session, company: Company, person_id: int, address: str, status: EmailStatus, provenance: str,
                source_id: int | None, confidence: int, now: datetime, evidence: str,
                verification: dict | None = None) -> None:
    """One row per person and address: a stronger status replaces a weaker one; a predicted address replaced by a
    better prediction for the same person is removed (one prediction per person)."""
    strength = {"invalid": 0, "unknown": 1, "predicted": 2, "high_confidence_predicted": 2.5, "catch_all": 3,
                "discovered": 4, "published": 4, "verified": 5, "confirmed": 6}
    row = db.scalar(select(Email).where(Email.person_id == person_id, Email.email == address))
    if status in (EmailStatus.PREDICTED, EmailStatus.HIGH_CONFIDENCE_PREDICTED, EmailStatus.CATCH_ALL):
        for old in db.scalars(select(Email).where(Email.person_id == person_id, Email.provenance == "predicted",
                                                  Email.email != address)):
            db.delete(old)
    if row is None:
        row = Email(person_id=person_id, company_id=company.id, email=address, email_type="work",
                    status=status.value, is_public=provenance == "public", confidence=confidence, source_id=source_id,
                    first_seen_at=now, provenance=provenance)
        db.add(row)
    elif strength.get(row.status, 0) > strength[status.value] or row.provenance in ("human_confirmed",
                                                                                    "internal_crm", "lusha"):
        row.last_seen_at = now
        return
    row.status, row.provenance, row.confidence = status.value, provenance, confidence
    row.evidence, row.last_seen_at = evidence[:500], now
    row.verification = {**(verification or {}), "checked_at": now.isoformat()} if verification is not None else \
        row.verification
    row.last_verified_at = now if status == EmailStatus.VERIFIED else None
    db.flush()
    db.add(ContactEvidence(email_id=row.id, kind=status.value, source_id=source_id, detail=evidence[:300],
                           observed_at=now))  # the address's evidence trail: this observation added, none replaced
