"""Read-only integration readiness for the Saasyto campaign transport."""
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.auth import get_admin
from app.config import get_settings
from app.models import AdminSession, AdminUser

router = APIRouter(prefix="/v1/communication", tags=["WhatsApp provider readiness"])


class ProviderStatus(BaseModel):
    provider: str
    transport: str
    delivery_enabled: bool
    local_test_mode: bool = False
    local_dynamic_mode: bool = False
    activation_cutoff: str | None = None
    sender_approved: bool
    credentials_configured: bool
    webhook_verified: bool
    connection_tested: bool
    notice: str


@router.get("/provider/saasyto", response_model=ProviderStatus)
def saasyto_status(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
) -> ProviderStatus:
    """No credentials, tokens, donor data or connection probes are returned."""
    cfg = get_settings()
    response.headers["Cache-Control"] = "no-store"
    credentials = bool(cfg.saasyto_instance_id and cfg.saasyto_access_token)
    return ProviderStatus(
        provider="Saasyto",
        transport="one_text_per_recipient",
        delivery_enabled=cfg.saasyto_delivery_enabled,
        local_test_mode=(
            getattr(cfg, "saasyto_local_test_enabled", False)
            or getattr(cfg, "saasyto_local_dynamic_enabled", False)
        ),
        local_dynamic_mode=getattr(cfg, "saasyto_local_dynamic_enabled", False),
        activation_cutoff=(
            cfg.saasyto_enable_after.isoformat()
            if getattr(cfg, "saasyto_enable_after", None) else None
        ),
        sender_approved=cfg.saasyto_sender_approved,
        credentials_configured=credentials,
        webhook_verified=False,
        connection_tested=False,
        notice=(
            "Dynamic localhost testing is enabled for explicitly reviewed and "
            "consented CRM recipients. Provider delivery is unverified."
            if cfg.saasyto_delivery_enabled and
            getattr(cfg, "saasyto_local_dynamic_enabled", False) else
            "Local pilot is active for explicitly allowlisted recipients; WhatsApp delivery "
            "and webhooks are still unverified."
            if cfg.saasyto_delivery_enabled and
            getattr(cfg, "saasyto_local_test_enabled", False) else
            "Saasyto transport enabled by the administrator, but message delivery "
            "and webhook confirmations have not been verified."
            if cfg.saasyto_delivery_enabled else
            "Saasyto campaign sending is disabled. Campaign review is safe and "
            "does not submit WhatsApp messages."
        ),
    )
