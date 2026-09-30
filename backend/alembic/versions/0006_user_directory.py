"""user display name and event creator on delete set null

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"; down_revision = "0005"; branch_labels = None; depends_on = None


def upgrade():
    op.add_column("users", sa.Column("name", sa.String(120), nullable=True))
    op.alter_column("events", "creator_id", existing_type=sa.String(36), nullable=True)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_creator_id_fkey")
        op.execute("ALTER TABLE events ADD CONSTRAINT events_creator_id_fkey FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE SET NULL")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_creator_id_fkey")
        op.execute("ALTER TABLE events ADD CONSTRAINT events_creator_id_fkey FOREIGN KEY (creator_id) REFERENCES users(id)")
    op.alter_column("events", "creator_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("users", "name")
