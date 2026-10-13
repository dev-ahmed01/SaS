"""Foundation-approved sponsorship commitment policy (INR and paise).

The multiple applies to new recurring agreements, not to partial receipts,
reversals, or outgoing payouts. Existing effective-dated rates stay immutable.
"""

SPONSORSHIP_STEP_PAISE = 25_000
SPONSORSHIP_DEFAULT_PAISE = SPONSORSHIP_STEP_PAISE
INACTIVITY_COMPLETED_MONTHS = 2
MAX_COMMITMENT_PAISE = 1_000_000_000


def valid_commitment(amount_paise: int) -> bool:
    return (
        isinstance(amount_paise, int)
        and not isinstance(amount_paise, bool)
        and SPONSORSHIP_STEP_PAISE <= amount_paise <= MAX_COMMITMENT_PAISE
        and amount_paise % SPONSORSHIP_STEP_PAISE == 0
    )
