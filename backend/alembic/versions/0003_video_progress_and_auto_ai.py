"""video progress and automatic AI analysis

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision="0003";down_revision="0002";branch_labels=None;depends_on=None


def upgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("videos")}
    if "processing_progress" not in columns:
        op.add_column("videos",sa.Column("processing_progress",sa.Integer(),nullable=False,server_default="0"))
    if "analyze_after_processing" not in columns:
        op.add_column("videos",sa.Column("analyze_after_processing",sa.Boolean(),nullable=False,server_default=sa.false()))


def downgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("videos")}
    if "analyze_after_processing" in columns:op.drop_column("videos","analyze_after_processing")
    if "processing_progress" in columns:op.drop_column("videos","processing_progress")
