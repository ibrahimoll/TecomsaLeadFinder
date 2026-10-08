"""Generate FICTIONAL Odoo export files for testing the import workflow.

    python -m scripts.sample_odoo_files            # writes ../samples/odoo_crm.xlsx and odoo_contacts.xlsx

The column headers follow Odoo's default English export labels. Every company,
person, email and phone number here is invented (example.* domains).
"""

import csv
import io
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

CRM_HEADERS = ["ID", "Opportunity", "Customer", "Contact Name", "Email", "Phone", "Salesperson", "Sales Team",
               "Stage", "Type", "Expected Revenue", "Probability", "Active", "Lost Reason", "Created on",
               "Last Updated on"]
CRM_ROWS = [
    [101, "ERP rollout - ABC Foods", "ABC Foods S.A.L.", "Rami Khoury", "rami@abcfoods.example", "+961 1 111 222",
     "Nadine Haddad", "Beirut Team", "Proposition", "Opportunity", 25000, 40, True, None,
     datetime(2026, 5, 4, 9, 30), datetime(2026, 9, 20, 16, 0)],
    [102, "WhatsApp automation - Cedar Hotels", "Cedar Hotels SAL", "Maya Saad", "maya@cedarhotels.example",
     "+961 4 222 333", "Karim Nassar", "Beirut Team", "Won", "Opportunity", 12000, 100, True, None,
     datetime(2026, 2, 11, 10, 0), datetime(2026, 6, 1, 12, 0)],
    [103, "POS for Byblos Bakery", "Byblos Bakery", "Tony Aoun", "tony@byblosbakery.example", "09 333 444",
     "Nadine Haddad", "North Team", "Qualified", "Opportunity", 4000, 10, False, "Too expensive",
     datetime(2025, 11, 2, 8, 0), datetime(2026, 1, 15, 9, 0)],
    [101, "ERP rollout - ABC Foods", "ABC Foods S.A.L.", "Rami Khoury", "rami@abcfoods.example", "+961 1 111 222",
     "Nadine Haddad", "Beirut Team", "Proposition", "Opportunity", 25000, 40, True, None,
     datetime(2026, 5, 4, 9, 30), datetime(2026, 9, 20, 16, 0)],  # exported twice: a duplicate row
    [None, None, None, "Unknown", None, None, None, None, "New", "Lead", None, None, True, None, None, None],
    [104, "Inbound website enquiry", "Tripoli Traders", "Sami Rifai", "sami@tripolitraders.example",
     "06 444 555", "Karim Nassar", "North Team", "New", "Lead", None, 5, True, None,
     datetime(2026, 9, 1, 11, 0), datetime(2026, 9, 2, 11, 0)],
]

CONTACT_HEADERS = ["ID", "Name", "Is a Company", "Company", "Job Position", "Email", "Phone", "Mobile", "City",
                   "Country"]
CONTACT_ROWS = [
    [501, "ABC FOODS", True, None, None, "info@abcfoods.example", "01 111 222", None, "Beirut", "Lebanon"],
    [502, "Rami Khoury", False, "ABC Foods", "Procurement Manager", "rami@abcfoods.example", None,
     "+961 3 555 666", "Beirut", "Lebanon"],
    [505, "Mohammad Hassan", False, "ABC Foods SAL", "General Manager", "m.hassan@abcfoods.example",
     "01 111 223", "+961 3 777 888", "Beirut", "Lebanon"],
    [503, "Mount Lebanon Pharma", True, None, None, "contact@mlpharma.example", "+961 5 777 888", None, "Baabda",
     "Lebanon"],
    [504, "Jane Doe", False, None, "Consultant", "jane.doe@gmail.com", None, "+961 70 123 456", "Jounieh",
     "Lebanon"],
]


def xlsx_bytes(headers: list, rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def csv_bytes(headers: list, rows: list) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return buffer.getvalue().encode("utf-8")


def main() -> int:
    target = Path(__file__).resolve().parents[2] / "samples"
    target.mkdir(exist_ok=True)
    (target / "odoo_crm.xlsx").write_bytes(xlsx_bytes(CRM_HEADERS, CRM_ROWS))
    (target / "odoo_contacts.xlsx").write_bytes(xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS))
    print(f"Wrote fictional sample files to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
