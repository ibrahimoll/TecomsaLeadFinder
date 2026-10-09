"""Mailbox connector (IMAP, read-only): the signature blocks of business e-mails a user received, into the
contributions pipeline (EMAIL_SIGNATURE: name, title, company, mobile, direct line, extension, WhatsApp). The user
connects their own mailbox on purpose; only signatures are read (never bodies, never stored), dry run first.

    MAILBOX_PASSWORD=... python -m app.services.mailbox LOGIN [--host imappro.zoho.com] [--days 365]
                                                       [--owner EMAIL] [--visibility ...] [--apply]

Zoho: IMAP must be enabled (Settings > Mail Accounts > IMAP); with two-factor authentication use an application-specific
password. Organisation accounts use imappro.zoho.com, personal ones imap.zoho.com.

Skipped: the user's own domain (colleagues), bulk / no-reply mail (newsletters, notifications), a message whose
sender's name never appears on its own line (no signature block to anchor on).
"""

import email
import html
import imaplib
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr

from app.services.contact_intelligence import FREE_MAIL
from app.services.contributions import BusinessContactConnector

SIGNATURE_LINES = 10  # the name line + what follows it
QUOTE = re.compile(r"^(>|on .{5,200} wrote:|-{2,} ?original message|from: .+@|de ?: .+@|sent from my )", re.IGNORECASE)
# a phone on a line: international (+961 / 00961), labelled (Tel: / M. / Mobile ...) or local (03 123 456, 01-234567)
PHONE = re.compile(r"(?:\+|\b00)\d[\d\s().-]{6,}\d|\b(?:tel|mob(?:ile)?|cell|phone|gsm|whats\s?app|[mtp])\s*[.:]\s*\+?\d"
                   r"[\d\s().-]{5,}\d|\b0\d[\d\s.-]{5,}\d", re.IGNORECASE)
NO_REPLY = re.compile(r"no-?reply|notifications?@|mailer-daemon|newsletter|bounce", re.IGNORECASE)


def _text(message: email.message.Message) -> str:
    plain = html_part = None
    for part in message.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = text
        elif part.get_content_type() == "text/html" and html_part is None:
            html_part = text
    if plain is None and html_part:
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", html_part)
        text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text)
        plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return plain or ""


def _same_person(line: str, name: str) -> bool:
    """'Jessy Ghobril' for the From name 'Jess Ghobril': the same surname, one first name a prefix of the other."""
    words, wanted = line.casefold().split(), name.casefold().split()
    return (len(wanted) >= 2 and 2 <= len(words) <= 4 and words[-1] == wanted[-1]
            and (words[0].startswith(wanted[0]) or wanted[0].startswith(words[0])))


def signature_block(body: str, sender_name: str) -> str | None:
    """The sender's own part (before any quoted reply / forward): from the last line that starts with their name;
    else the lines around its last phone number, under their From name (a person's name: 2-4 words of letters)."""
    own = []
    for line in body.replace("\r", "").split("\n"):
        if QUOTE.match(line.strip()):
            break
        # "Karim Aoun | IT Manager | Omega Foods": one field per line
        own += [" ".join(part.split()) for part in re.split(r"\s+[|•]\s+", line)] or [""]
    name = " ".join(sender_name.split())
    if len(name) >= 4:
        starts = [i for i, line in enumerate(own) if line.casefold().startswith(name.casefold())
                  or _same_person(line, name)]
        if starts:
            first, *rest = [line for line in own[starts[-1]:starts[-1] + SIGNATURE_LINES] if line]
            if not first.casefold().startswith(name.casefold()):
                return "\n".join([first] + rest)  # the signature's own spelling of the name
            # "Karim Aoun - IT Manager": the name, then the rest of its line as the next one
            tail = first[len(name):].strip(" |-–,")
            return "\n".join([name] + ([tail] if tail else []) + rest)
    phones = [i for i, line in enumerate(own) if PHONE.search(line)]
    if not phones or not re.fullmatch(r"[^\W\d_]+(?:[ '.-][^\W\d_]+){1,3}", name):
        return None
    end, start = phones[-1], phones[-1]
    while start > 0 and own[start - 1] and end - start < SIGNATURE_LINES - 2:  # up to the blank line above
        start -= 1
    return "\n".join([name] + [line for line in own[start:end + 3] if line])


def signatures_from(messages, own_domain: str, stats: Counter | None = None) -> list[str]:
    """messages: email.message.Message objects -> one signature per sender (their newest). stats: why skipped."""
    stats = stats if stats is not None else Counter()
    newest: dict[str, str] = {}
    for message in messages:
        stats["messages"] += 1
        name, address = parseaddr(str(make_header(decode_header(message.get("From", "")))))
        address = address.lower()
        reason = ("no_sender" if not address else "own_domain" if address.endswith("@" + own_domain)
                  else "no_reply" if NO_REPLY.search(address)
                  else "bulk" if message.get("List-Unsubscribe") or (message.get("Precedence") or "").lower()
                  in ("bulk", "list") else "sender_done" if address in newest else None)
        if reason:
            stats[f"skipped_{reason}"] += 1
            continue
        if block := signature_block(_text(message), name):
            # the sender's address names their company (its domain) when the signature itself has none
            newest[address] = block if "@" in block else f"{block}\n{address}"
        else:
            stats["skipped_no_signature"] += 1
    stats["senders_with_signature"] = len(newest)
    return list(newest.values())


class ImapConnector(BusinessContactConnector):
    def __init__(self, login: str, password: str, *, host: str = "imappro.zoho.com", days: int = 365,
                 folder: str = "INBOX"):
        self.login, self.password, self.host, self.days, self.folder = login, password, host, days, folder
        self.stats: Counter = Counter()

    def signatures(self) -> list[str]:
        if hasattr(self, "found"):  # downloaded once per run
            return self.found
        since = (datetime.now(timezone.utc) - timedelta(days=self.days)).strftime("%d-%b-%Y")
        with imaplib.IMAP4_SSL(self.host) as imap:
            imap.login(self.login, self.password)
            imap.select(self.folder, readonly=True)  # nothing is marked read, moved or deleted
            _, data = imap.search(None, "SINCE", since)
            ids = data[0].split()[::-1]  # newest first: a sender's latest signature wins
            messages = []
            for start in range(0, len(ids), 200):
                _, parts = imap.fetch(b",".join(ids[start:start + 200]), "(BODY.PEEK[]<0.200000>)")  # text only
                messages += [email.message_from_bytes(p[1]) for p in parts if isinstance(p, tuple)]
        self.found = signatures_from(messages, self.login.split("@")[-1].lower(), self.stats)
        return self.found


if __name__ == "__main__":
    import argparse
    import json
    import os

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Company, User
    from app.models.enums import VISIBILITIES
    from app.services import contributions

    parser = argparse.ArgumentParser()
    parser.add_argument("login", help="the mailbox address (its password in MAILBOX_PASSWORD)")
    parser.add_argument("--host", default="imappro.zoho.com")
    parser.add_argument("--folder", default="INBOX")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--owner", help="the LeadFinder user these contacts belong to (default: the login)")
    parser.add_argument("--visibility", choices=VISIBILITIES, default="managers")
    parser.add_argument("--add-companies", action="store_true",
                        help="look up each sender domain LeadFinder does not know (Search: created on strong evidence)")
    parser.add_argument("--apply", action="store_true", help="write the contacts (default: dry run)")
    args = parser.parse_args()
    connector = ImapConnector(args.login, os.environ["MAILBOX_PASSWORD"], host=args.host, days=args.days,
                              folder=args.folder)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == (args.owner or args.login)))
        if user is None:
            raise SystemExit(f"no LeadFinder user {args.owner or args.login}: pass --owner")
        found = connector.signatures()
        parsed = [e for e in map(contributions.parse_signature, found) if e]
        # the senders' companies, by e-mail domain (domains only, never names)
        domains = Counter(d for e in parsed if e.get("email")
                          if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}", d := e["email"].split("@")[1].lower()))
        known = set(session.scalars(select(Company.domain).where(Company.domain.in_(list(domains) or [""]))))
        unknown = [d for d, _ in domains.most_common() if d not in known and d not in FREE_MAIL]
        lookups = {}
        if args.add_companies:
            from app.services import company_search

            for domain in unknown:
                result = company_search.lookup(session, domain, user_id=user.id)
                lookups[domain] = result["status"]
                session.commit()
        report = contributions.sync(session, connector, user, visibility=args.visibility, apply=args.apply)
        print(json.dumps({"mailbox": dict(connector.stats),
                          "signatures": {"total": len(parsed), "with_title": sum("title" in e for e in parsed),
                                         "with_mobile": sum("mobile" in e or "whatsapp" in e for e in parsed),
                                         "with_phone_or_extension": sum("phone" in e or "extension" in e
                                                                        for e in parsed)},
                          "pipeline": {k: v for k, v in report["signatures"].items() if k != "review"},
                          "company_lookups": lookups, "unknown_domains": unknown, "known_domains": sorted(known)},
                         ensure_ascii=False, indent=1, default=str))
