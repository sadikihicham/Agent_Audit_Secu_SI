"""initial schema: users, machines, metrics (hypertable), alerts

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("os", sa.String(length=128), nullable=True),
        sa.Column("enroll_token_hash", sa.String(length=255), nullable=True),
        sa.Column("agent_version", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enroll_token_hash"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alerts_machine_id"), "alerts", ["machine_id"], unique=False)

    op.create_table(
        "metrics",
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_pct", sa.Float(), nullable=False),
        sa.Column("mem_pct", sa.Float(), nullable=False),
        sa.Column("disk_pct", sa.Float(), nullable=False),
        sa.Column("uptime_s", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        # La colonne de partitionnement (time) doit faire partie de la PK.
        sa.PrimaryKeyConstraint("machine_id", "time"),
    )
    # Conversion en hypertable TimescaleDB sur la dimension temporelle.
    op.execute("SELECT create_hypertable('metrics', 'time', if_not_exists => TRUE);")


def downgrade() -> None:
    op.drop_table("metrics")
    op.drop_index(op.f("ix_alerts_machine_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("machines")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
