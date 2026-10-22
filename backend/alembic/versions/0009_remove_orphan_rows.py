"""remove rows orphaned while SQLite foreign keys were not enforced

The SQLite (desktop) engine never switched foreign-key enforcement on, so
deleting a match or video left dependent rows behind. Apply to those rows
exactly the ON DELETE rule the schema declares: CASCADE deletes them, SET NULL
clears the reference; anything else is only logged. PostgreSQL always enforced
the rules, so it has nothing to clean.

Revision ID: 0009
Revises: 0008
"""
import logging
from alembic import op

revision = "0009"; down_revision = "0008"; branch_labels = None; depends_on = None
log = logging.getLogger("alembic.runtime.migration")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    connection = bind.connection.driver_connection
    for _ in range(20):  # a CASCADE delete can orphan the next level down
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if not violations:
            return
        changed = False
        for table, rowid, parent, fk_id in violations:
            if rowid is None:
                continue
            rule = next(((column, on_delete) for (id_, _seq, _parent, column, _to, _upd, on_delete, _match)
                         in connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall() if id_ == fk_id), None)
            if not rule:
                continue
            column, on_delete = rule
            if on_delete == "CASCADE":
                connection.execute(f'DELETE FROM "{table}" WHERE rowid = ?', (rowid,)); changed = True
                log.info("Removed orphan %s row %s (missing %s)", table, rowid, parent)
            elif on_delete == "SET NULL":
                connection.execute(f'UPDATE "{table}" SET "{column}" = NULL WHERE rowid = ?', (rowid,)); changed = True
                log.info("Cleared orphan reference %s.%s row %s (missing %s)", table, column, rowid, parent)
            else:
                log.warning("Orphan %s row %s references missing %s (%s): left untouched", table, rowid, parent, on_delete)
        if not changed:
            return


def downgrade():
    pass  # deleted orphans cannot be restored; they were unreachable already
