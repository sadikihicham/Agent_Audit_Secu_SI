"""machines.hostname nullable (renseigné à l'enrôlement)

Revision ID: 0002_hostname_nullable
Revises: 0001_initial
Create Date: 2026-05-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0002_hostname_nullable"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("machines", "hostname", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.alter_column("machines", "hostname", existing_type=sa.String(length=255), nullable=False)
