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
MAX_OUTBOUND_LENGTH = 1200
# The CRM limits full_name to 160 chars; each template token may repeat.
# Allow generous room for legacy amounts and descriptive subscription labels.
WORST_CASE_REPLACEMENT_LENGTH = {
    "name": 160, "code": 4, "sponsorship": 64,
    "sponsorship_amount": 28, "sponsorship_units": 20,
}


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
    largest_render = TOKEN.sub(
        lambda match: "X" * WORST_CASE_REPLACEMENT_LENGTH[match.group(1)],
        body,
    )
    if len(largest_render) > MAX_OUTBOUND_LENGTH:
        raise ValueError("Activation message is too long after personalization")
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
    if amount <= 0:
        raise ValueError("Prospect has no monthly sponsorship commitment")
    # Legacy agreements may not be a multiple of the new ₹250 tier. Preserve
    # their actual amount; never block activation or silently reprice a donor.
    tiered = amount % SPONSORSHIP_STEP_PAISE == 0
    units = amount // SPONSORSHIP_STEP_PAISE if tiered else None
    rupees, paise = divmod(amount, 100)
    money = f"₹{rupees:,}" + (f".{paise:02d}" if paise else "")
    replacements = {
        "name": prospect.first_name or prospect.full_name,
        "code": code,
        "sponsorship_amount": money,
        "sponsorship_units": str(units) if units is not None else "Not applicable",
        # State the actual monthly amount; never append ₹250 unit breakdowns.
        "sponsorship": money + " per month",
    }
    message = TOKEN.sub(
        lambda match: replacements[match.group(1)], validate_otp_body(body),
    )
    if len(message) > MAX_OUTBOUND_LENGTH:
        raise ValueError("Rendered activation message is too long")
    return message
