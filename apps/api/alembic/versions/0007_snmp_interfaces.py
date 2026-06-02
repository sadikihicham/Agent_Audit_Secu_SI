"""enrichissement SNMP : colonnes système sur devices + table device_interfaces

Revision ID: 0007_snmp_interfaces
Revises: 0006_network_events
Create Date: 2026-06-01

"""
from alembic import op
import sqlalchemy as sa

revision = "0007_snmp_interfaces"
down_revision = "0006_network_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Colonnes SNMP (groupe système) sur les appareils.
    op.add_column(
        "devices",
        sa.Column(
            "snmp_reachable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("devices", sa.Column("sys_descr", sa.Text(), nullable=True))
    op.add_column(
        "devices", sa.Column("sys_uptime_secs", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "devices", sa.Column("sys_location", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "devices", sa.Column("sys_contact", sa.String(length=255), nullable=True)
    )

    # Table des interfaces réseau (ifTable SNMP).
    op.create_table(
        "device_interfaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("mac", sa.String(length=17), nullable=True),
        sa.Column("admin_up", sa.Boolean(), nullable=True),
        sa.Column("oper_up", sa.Boolean(), nullable=True),
        sa.Column("speed_bps", sa.BigInteger(), nullable=True),
        sa.Column("mtu", sa.Integer(), nullable=True),
        sa.Column("in_octets", sa.BigInteger(), nullable=True),
        sa.Column("out_octets", sa.BigInteger(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id", "if_index", name="uq_device_interface_index"
        ),
    )
    op.create_index(
        op.f("ix_device_interfaces_device_id"),
        "device_interfaces",
        ["device_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_device_interfaces_device_id"), table_name="device_interfaces"
    )
    op.drop_table("device_interfaces")
    op.drop_column("devices", "sys_contact")
    op.drop_column("devices", "sys_location")
    op.drop_column("devices", "sys_uptime_secs")
    op.drop_column("devices", "sys_descr")
    op.drop_column("devices", "snmp_reachable")
