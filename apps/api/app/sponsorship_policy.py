"""Foundation-approved sponsorship commitment policy (INR and paise).

The ₹250 tier applies to newly agreed sponsorship commitments AND all new
manually recorded incoming contributions. Existing financial entries, audited
reversals, and outgoing payouts are unaffected; old rates stay effective-dated.
"""

SPONSORSHIP_STEP_PAISE = 25_000
SPONSORSHIP_DEFAULT_PAISE = SPONSORSHIP_STEP_PAISE
INACTIVITY_COMPLETED_MONTHS = 2
MAX_COMMITMENT_PAISE = 1_000_000_000


def valid_contribution(amount_paise: int) -> bool:
    return (
        isinstance(amount_paise, int)
        and not isinstance(amount_paise, bool)
        and SPONSORSHIP_STEP_PAISE <= amount_paise <= MAX_COMMITMENT_PAISE
        and amount_paise % SPONSORSHIP_STEP_PAISE == 0
    )


def valid_commitment(amount_paise: int) -> bool:
    """Sponsorship agreements follow the same allowed incoming denomination."""
    return valid_contribution(amount_paise)
