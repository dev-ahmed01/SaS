"""Organization staff roles; existing admins keep owner privileges.

Revision ID: 0026_admin_roles
Revises: 0025_payout_reversal
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_admin_roles"
down_revision = "0025_payout_reversal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admin_users") as batch:
        batch.add_column(
            sa.Column("role", sa.String(16), nullable=False, server_default="owner")
        )
        batch.create_check_constraint(
            "ck_admin_user_role",
            "role IN ('owner', 'crm', 'finance', 'messaging', 'viewer')",
        )


def downgrade() -> None:
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_constraint("ck_admin_user_role", type_="check")
        batch.drop_column("role")
