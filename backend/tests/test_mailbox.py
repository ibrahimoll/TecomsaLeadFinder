"""Mailbox connector: only the sender's own signature block of a business e-mail is read (quoted replies, colleagues,
newsletters and no-reply senders skipped), then the contributions pipeline attaches the mobile to the person."""

from email.message import EmailMessage

from sqlalchemy import select

from app.models import Phone
from app.models.enums import UserRole
from app.services import contributions, mailbox
from tests.test_contacts import omega, person_id
from tests.test_enrichment import research, site  # noqa: F401 - the mocked-web fixture


def message(sender: str, body: str, html: bool = False, **headers) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"] = sender, "ahmad@tecomsa.example"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body, subtype="html" if html else "plain")
    return m


KARIM = """Hi Ahmad,

Please send the Odoo proposal.

Best regards,
Karim Aoun
IT Manager
Omega Foods SAL
Mobile: +961 3 123 456
Tel: +961 8 800 800 ext. 214

On Mon, 5 Oct 2026, Ahmad wrote:
> Lina Khoury
> Finance Director
> M: +961 3 999 999"""


def test_signatures_only_from_business_senders_own_part():
    found = mailbox.signatures_from([
        message("Karim Aoun <karim.aoun@omegafoods.example>", KARIM),
        message("Karim Aoun <karim.aoun@omegafoods.example>", "Older\n\nKarim Aoun\nIT Manager\nM: 03 000 000"),
        message("Sami <sami@tecomsa.example>", "Sami\nSales\nM: +961 3 555 555"),  # a colleague
        message("Promo <news@shop.example>", "Promo\nM: +961 3 444 444", List_Unsubscribe="<mailto:x>"),
        message("Rita Saad <rita@acme.example>", "<p>Thanks</p><p>Rita Saad<br>CFO<br>M: +961 70 111 222</p>", True),
    ], own_domain="tecomsa.example")
    assert len(found) == 2
    karim = contributions.parse_signature(found[0])
    assert karim["person"] == "Karim Aoun" and karim["title"] == "IT Manager"
    assert karim["mobile"] == "+961 3 123 456" and karim["extension"] == "214"
    assert "999" not in found[0]  # the quoted reply is someone else's
    rita = contributions.parse_signature(found[1])
    assert rita["mobile"] == "+961 70 111 222" and rita["email"] == "rita@acme.example"  # sender's address added


def test_mailbox_sync_attaches_the_mobile(client_for, db, site):  # noqa: F811
    agent, user = client_for(UserRole.SALES_AGENT)
    company_id = omega(agent, site)
    research(agent, company_id)

    class Fake(mailbox.ImapConnector):
        def signatures(self):
            return mailbox.signatures_from([message("Karim Aoun <karim.aoun@omegafoods.example>", KARIM)],
                                           "tecomsa.example")
    dry = contributions.sync(db, Fake("ahmad@tecomsa.example", "x"), user)
    assert dry["signatures"]["phones_added_business_mobile"] == 1
    assert not db.scalar(select(Phone.id).where(Phone.person_id == person_id(db, "Karim Aoun"),
                                                Phone.phone_type == "business_mobile"))  # dry run: nothing written
    contributions.sync(db, Fake("ahmad@tecomsa.example", "x"), user, apply=True)
    assert db.scalar(select(Phone.id).where(Phone.person_id == person_id(db, "Karim Aoun"),
                                            Phone.phone_type == "business_mobile"))


def test_name_and_title_on_one_line_and_phone_fallback():
    one_line = mailbox.signature_block("Thanks\n\nKarim Aoun | IT Manager\nOmega Foods\nM: +961 3 123 456", "Karim Aoun")
    karim = contributions.parse_signature(one_line)
    assert (karim["person"], karim["title"], karim["mobile"]) == ("Karim Aoun", "IT Manager", "+961 3 123 456")
    # no line with the name (signed "K."): the block around the last phone, under the From name
    fallback = mailbox.signature_block("Noted, thanks.\n\nK.\nFinance Director\nOmega Foods\nMob. 03 123 456\n\n"
                                       "On Mon, 5 Oct 2026, Ahmad wrote:\n> M: 03 999 999", "Rita Saad")
    rita = contributions.parse_signature(fallback)
    assert rita["person"] == "Rita Saad" and rita["mobile"] == "03 123 456" and "999" not in fallback
    assert mailbox.signature_block("See the invoice dated 2026-10-05.", "Omega Foods SAL") is None  # not a person


def test_one_line_signature_with_a_differently_spelled_name():
    block = mailbox.signature_block("Thanks\n\nJessy Ghobril | E-commerce Specialist | Mozart Chahine S.A.R.L\n"
                                    "M: +961 76 000 000", "Jess Ghobril")
    jessy = contributions.parse_signature(block)
    assert (jessy["person"], jessy["title"], jessy["company"]) == ("Jessy Ghobril", "E-commerce Specialist",
                                                                   "Mozart Chahine S.A.R.L")
