"""Tenant-scoped, editable Saasyto registration OTP copy.

Only the selected prospect's current CRM commitment and fresh server-generated
code may be interpolated. This is NOT a campaign/automation message.
"""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommunicationTemplate, Prospect
from app.sponsorship_policy import SPONSORSHIP_STEP_PAISE

OTP_TEMPLATE_KEY = "__system_sponsor_otp__"
OTP_TEMPLATE_NAME = "Sponsorship registration OTP"
DEFAULT_OTP_BODY = (
    "Salaam {{name}},\n\n"
    "Thank you for taking this step and helping us re-establish Namaz "
    "in the house of Allah.\n\n"
    "*Sponsorship details*\n"
    "Monthly sponsorship: {{sponsorship}}\n"
    "Please make your contribution by the 7th of every month.\n\n"
    "*Your authentication code to register this sponsorship: {{code}}*\n"
    "Valid for 2 minutes."
)
TOKEN = re.compile(r"{{\s*([a-z_]+)\s*}}")
UNKNOWN = re.compile(r"{{.*?}}", re.DOTALL)
ALLOWED = {"name", "code", "sponsorship", "sponsorship_amount", "sponsorship_units"}


def validate_otp_body(body: str) -> str:
    body = body.strip()
    tokens = TOKEN.findall(body)
    if not 30 <= len(body) <= 1200:
        raise ValueError("Activation message must contain 30 to 1200 characters")
    if tokens.count("code") != 1:
        raise ValueError("Include {{code}} exactly once")
    if "name" not in tokens:
        raise ValueError("Include {{name}}")
    if not {"sponsorship", "sponsorship_amount"}.intersection(tokens):
        raise ValueError("Include {{sponsorship}} or {{sponsorship_amount}}")
    if any(token not in ALLOWED for token in tokens) or UNKNOWN.search(TOKEN.sub("", body)):
        raise ValueError("Unsupported message variable")
    return body


def template_body(db: Session, org: uuid.UUID) -> str:
    row = db.scalars(select(CommunicationTemplate.body).where(
        CommunicationTemplate.organization_id == org,
        CommunicationTemplate.name_key == OTP_TEMPLATE_KEY,
        CommunicationTemplate.archived_at.is_(None),
    )).one_or_none()
    return row or DEFAULT_OTP_BODY


def render_otp(body: str, prospect: Prospect, code: str) -> str:
    """No default/fallback name or contribution: use the selected CRM record."""
    amount = prospect.monthly_contribution_paise
    if amount <= 0 or amount % SPONSORSHIP_STEP_PAISE:
        raise ValueError("Prospect has no valid monthly sponsorship commitment")
    units = amount // SPONSORSHIP_STEP_PAISE
    money = f"₹{amount // 100:,}"
    replacements = {
        "name": prospect.first_name or prospect.full_name,
        "code": code,
        "sponsorship_amount": money,
        "sponsorship_units": str(units),
        "sponsorship": (
            money + " per month" +
            (f" ({units} units at ₹250 each)" if units > 1 else "")
        ),
    }
    return TOKEN.sub(lambda match: replacements[match.group(1)], validate_otp_body(body))
