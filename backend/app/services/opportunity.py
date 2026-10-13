"""Opportunity fit (Sales AI, step 1: rules). Per TECOMSA solution, points from what LeadFinder already knows about
the company - its signals (website research), industry (directory / discovery), social links, size, sales status -
each point with its reason and evidence, the modules / services to pitch and the people to call.

    fit     >= 6 high, 3-5 medium, 1-2 low; 0 points is "unknown" (not enough data) unless the company's website was
            researched (then low: we looked and saw nothing)
    never   a made-up fact: a reason only cites a signal / field LeadFinder stores. Computed live (never stale); the
            opportunity_analysis table is left for the AI-written pitch (step 2).
ponytail: hand-set points; step 3 lets the Scout re-weight them from the deals the team actually wins.
"""

import re
from typing import Any

from app.models import Company

# (signal types, technology / provider values, industry words, points, why, pitch)
Rule = tuple[tuple[str, ...], tuple[str, ...], str | None, int, str, str | None]

RULES: dict[str, list[Rule]] = {
    "odoo": [
        (("manufacturing", "factory", "private_label", "factory_opening", "news_new_factory"), (),
         r"manufactur|factory|industr|production|bakery|food process|printing", 3,
         "Makes products: production, stock and costing", "Manufacturing, Inventory, Quality"),
        (("distribution", "wholesale", "importing", "exporting", "warehouse", "distribution_center",
          "warehouse_opening", "distribution_agreement"), (), r"trading|distribut|wholesale|import|export|logistic", 3,
         "Buys, stocks and resells", "Inventory, Purchase, Sales"),
        (("retail", "retail_stores", "e_commerce", "online_ordering", "showrooms", "ecommerce_launch"),
         ("WooCommerce", "Shopify"), r"retail|shop|store|pharmac|supermarket|boutique", 2,
         "Sells in stores or online", "Point of Sale, eCommerce, Inventory"),
        (("construction", "project_based", "procurement_award"), (),
         r"contract|construct|engineer|real estate|architect", 2, "Runs projects", "Project, Timesheets, Invoicing"),
        (("hospitality", "healthcare", "clinics", "hospitals", "restaurants", "appointment_booking",
          "professional_services"), (), r"restaurant|hotel|clinic|hospital|school|consult|travel|agency|service", 1,
         "Bills services or appointments", "Point of Sale / Appointments, Invoicing"),
        ((), (), r"\bbank|insurance|insurer", -2, "Banks and insurers run specialised core systems", None),
        (("multi_location", "branches", "franchising", "franchise_network", "branch_opening", "news_new_branch"), (),
         None, 2, "Several sites: one accounting and stock across them", "Multi-company Accounting"),
        (("fleet", "delivery", "field_sales"), (), None, 1, "Teams or vehicles on the road", "Field Service, Fleet"),
        (("active_careers_page", "job_openings", "hiring_department", "news_expansion", "expansion", "funding",
          "new_market", "news_new_market", "acquisition"), (), None, 1, "Growing: hiring or expanding", None),
    ],
    "frinzo": [
        (("retail", "retail_stores", "e_commerce", "hospitality", "restaurants", "healthcare", "clinics", "hospitals",
          "b2c"), (),
         r"restaurant|caf|hotel|hospitality|retail|shop|store|supermarket|clinic|hospital|medical|pharmac|beauty|salon|"
         r"school|universit|education|gym|real estate|travel|touris|car|auto|fashion|e-?commerce|deliver|bank|financ|"
         r"insurance",
         2, "Talks to many customers (customer-facing sector)", "WhatsApp and Instagram campaigns"),
        ((), ("Meta Pixel",), None, 2, "Already pays for Facebook / Instagram ads",
         "Re-engage ad audiences on WhatsApp"),
        (("customer_support", "call_center"), ("Tawk.to",), None, 3,
         "Several people answer customers (support, WhatsApp, live chat)", "WhatsApp chatbot and shared inbox"),
        (("online_ordering", "delivery", "appointment_booking"), (), None, 2, "Takes orders or bookings",
         "Order updates and booking reminders on WhatsApp"),
        ((), ("SendGrid", "Mailgun", "Mailchimp", "Brevo"), None, 1, "Already runs email campaigns",
         "SMS and WhatsApp next to email"),
        (("multi_location", "branches", "franchising", "franchise_network"), (), None, 1, "Several branches",
         "Campaigns per branch"),
    ],
    "it": [
        ((), ("Self-hosted e-mail", "Other e-mail host", "Hostinger e-mail", "Titan Mail", "Rackspace e-mail"), None,
         2, "Email on a basic host", "Microsoft 365 / Google Workspace migration"),
        ((), ("No DMARC policy", "DMARC p=none"), None, 2, "Its email domain can be spoofed (no enforced DMARC)",
         "Email security: SPF, DKIM, DMARC"),
        (("multi_location", "branches", "franchising", "franchise_network"), (), None, 2, "Several sites to connect",
         "Network, VPN, multi-site support"),
        (("hospitals", "clinics", "healthcare", "hospital_beds"), (), r"hospital|clinic|medical|laborator", 2,
         "Uptime and patient data matter", "Backup, security, managed IT"),
        ((), ("Microsoft 365",), None, 1, "Runs Microsoft 365", "Security, backup, licences"),
        (("manufacturing", "factory", "hospitality", "warehouse", "call_center", "retail_stores", "showrooms"), (),
         r"hotel|school|universit|factory|warehouse|mall|holding|group|logistic", 1,
         "Sites full of networks, Wi-Fi, CCTV and phones", "Network and Wi-Fi, CCTV, telephony"),
        (("branch_opening", "news_new_branch", "news_expansion", "news_new_factory", "warehouse_opening",
          "factory_opening", "expansion"), (), None, 2, "Opening a new site: network, Wi-Fi, CCTV and phones to install",
         "New-site network, Wi-Fi, CCTV and telephony"),
    ],
}
# Size (TECOMSA's ideal customers, 2026-10): (sweet spot min, max) and points; a known very small company is a bad fit.
SIZE = {"odoo": (20, 500, 2), "frinzo": (20, None, 1), "it": (20, 1000, 2)}
TINY = 10
SOLUTION_LABEL = {"odoo": "Odoo ERP", "frinzo": "Frinzo", "it": "IT solutions"}
# who to call, by department, in order: a small company (or one of unknown size) decides at the top
CALL = {"odoo": (["executive", "finance"], ["executive", "finance", "it", "operations", "supply_chain"]),
        "frinzo": (["executive", "marketing"],
                   ["marketing", "customer_experience", "e_commerce", "executive", "it", "sales"]),
        "it": (["executive", "it"], ["it", "executive", "operations", "procurement"])}
DEPARTMENT_LABEL = {"executive": "Owner / GM", "finance": "Finance", "operations": "Operations", "it": "IT",
                    "supply_chain": "Supply chain", "marketing": "Marketing", "e_commerce": "E-commerce",
                    "sales": "Sales", "customer_experience": "Customer service", "procurement": "Procurement"}


def _level(points: int, researched: bool) -> str:
    return "high" if points >= 6 else "medium" if points >= 3 else "low" if points or researched else "unknown"


def analyse(company: Company, signals: list[dict[str, Any]], people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """signals: company_detail's signal dicts; people: company_people rows (current ones are called)."""
    types = {s["signal_type"]: s.get("signal_value") for s in signals}
    values = {str(s.get("signal_value")) for s in signals if s.get("signal_value")}
    industry = " ".join(filter(None, (company.industry, company.sub_industry))).lower()
    researched = any(s["signal_type"] in ("technology", "email_provider", "email_security") for s in signals)
    small = (company.employee_count_max or company.employee_count_estimate or 0) <= 50
    staff = company.employee_count_estimate or company.employee_count_max or company.employee_count_min
    out = []
    for solution, rules in RULES.items():
        reasons, pitch = [], []
        for kinds, techs, words, points, why, offer in rules:
            hit = next((k for k in kinds if k in types), None)
            evidence = (f"{hit.replace('_', ' ')}{f': {types[hit]}' if types[hit] else ''}" if hit else
                        next((t for t in techs if t in values), None) or
                        (f"industry: {company.industry}" if words and industry and re.search(words, industry) else None))
            if evidence:
                reasons.append({"why": why, "evidence": evidence, "points": points})
                if offer and offer not in pitch:
                    pitch.append(offer)
        if solution == "frinzo" and (company.instagram_url or company.facebook_url):
            reasons.append({"why": "On Instagram / Facebook", "points": 1,
                            "evidence": " · ".join(n for n, u in (("Instagram", company.instagram_url),
                                                                   ("Facebook", company.facebook_url)) if u)})
        if staff:
            low, high, points = SIZE[solution]
            if staff <= TINY:
                reasons.append({"why": "Very small: simple operations, usually a bad fit", "points": -3,
                                "evidence": f"{staff} employees"})
            elif staff >= low:
                ideal = high is None or staff <= high
                reasons.append({"why": "The size TECOMSA sells to" if ideal else "Large organisation",
                                "points": points if ideal else 1, "evidence": f"{staff:,} employees"})
        total = sum(r["points"] for r in reasons)
        note = None
        if solution == "odoo" and "Odoo" in values:
            note = "Already uses Odoo: a support, upgrade or partner-switch conversation, not a new ERP sale."
        if company.status == f"working_{solution}":
            note = f"TECOMSA is already working {SOLUTION_LABEL[solution]} with this company."
        order = CALL[solution][0 if small else 1]
        current = [p for p in people if p.get("employment_status") != "former" and p.get("department") in order]
        current.sort(key=lambda p: (order.index(p["department"]), p.get("title_rank") or 99))
        out.append({"solution": solution, "label": SOLUTION_LABEL[solution], "fit_level": _level(total, researched),
                    "points": total, "reasons": sorted(reasons, key=lambda r: -r["points"]), "pitch": pitch,
                    "call": [DEPARTMENT_LABEL[d] for d in order], "note": note,
                    "people": [{"id": p["person"].id, "name": p["person"].full_name, "title": p["job_title"]}
                               for p in current[:3]]})
    return out
