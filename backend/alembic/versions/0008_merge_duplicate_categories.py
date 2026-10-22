"""merge duplicate seed categories

Four seed categories named the same gesture twice. Each removed category is
folded into the one that stays: events, templates, AI suggestion corrections
and user configuration (shortcut, clip rolls, enabled) move over, then the
duplicate is deleted. Matching is by exact name only, so a category the user
renamed is never touched.

Everything needed to undo the merge exactly is kept in `category_merges`
(original category rows) and `events.metadata.merged_from`, so downgrade()
restores the previous state.

Revision ID: 0008
Revises: 0007
"""
import logging
import uuid
from alembic import op
import sqlalchemy as sa

revision = "0008"; down_revision = "0007"; branch_labels = None; depends_on = None

MERGES = [("Ball Recovery", "Recovery"), ("Turnover Forced", "Forced Turnover"),
          ("Press", "Pressure"), ("Box Entry", "Penalty Area Entry")]
CATEGORY_FIELDS = ("id", "name", "icon", "shortcut", "order", "enabled", "pre_roll", "post_roll", "metadata_schema")
DEFAULT_ROLL = 5.0
log = logging.getLogger("alembic.runtime.migration")

categories = sa.table("categories", *[sa.column(name) for name in CATEGORY_FIELDS[:-1]], sa.column("metadata_schema", sa.JSON))
events = sa.table("events", sa.column("id"), sa.column("category_id"), sa.column("metadata", sa.JSON))
templates = sa.table("templates", sa.column("id"), sa.column("definition", sa.JSON))
suggestions = sa.table("ai_suggestions", sa.column("id"), sa.column("proposed_category"), sa.column("corrected_data", sa.JSON))
merges = sa.table("category_merges", sa.column("id"), sa.column("seq"), sa.column("removed", sa.JSON), sa.column("kept", sa.JSON),
                  sa.column("templates", sa.JSON), sa.column("suggestions", sa.JSON))


def _row(bind, name):
    row = bind.execute(sa.select(*[categories.c[f] for f in CATEGORY_FIELDS]).where(categories.c.name == name)).mappings().first()
    return dict(row) if row else None


def _swap_name(names, old, new):
    out = []
    for name in names:
        name = new if name == old else name
        if name not in out:
            out.append(name)
    return out


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("category_merges"):
        return
    op.create_table("category_merges", sa.Column("id", sa.String(36), primary_key=True), sa.Column("seq", sa.Integer, nullable=False),
                    sa.Column("removed", sa.JSON, nullable=False), sa.Column("kept", sa.JSON, nullable=True),
                    sa.Column("templates", sa.JSON, nullable=False), sa.Column("suggestions", sa.JSON, nullable=False))
    for seq, (old_name, new_name) in enumerate(MERGES):
        removed = _row(bind, old_name)
        if not removed:
            continue
        kept = _row(bind, new_name)
        if not kept:
            # Only the duplicate exists (older or customised database): rename it.
            bind.execute(categories.update().where(categories.c.id == removed["id"]).values(name=new_name))
            bind.execute(merges.insert().values(id=str(uuid.uuid4()), seq=seq, removed=removed, kept=None, templates=[], suggestions=[]))
            log.info("Category %r renamed to %r", old_name, new_name)
            continue
        # Events keep a record of their original category for downgrade().
        for event_id, metadata in bind.execute(sa.select(events.c.id, events.c.metadata).where(events.c.category_id == removed["id"])).all():
            bind.execute(events.update().where(events.c.id == event_id).values(
                category_id=kept["id"], metadata={**(metadata or {}), "merged_from": old_name}))
        changed_templates = []
        for template_id, definition in bind.execute(sa.select(templates.c.id, templates.c.definition)).all():
            definition = dict(definition or {})
            names = definition.get("categories") or []
            if old_name not in names:
                continue
            changed_templates.append({"id": template_id, "categories": list(names), "qualifiers": definition.get("qualifiers")})
            definition["categories"] = _swap_name(names, old_name, new_name)
            qualifiers = dict(definition.get("qualifiers") or {})
            if old_name in qualifiers:
                qualifiers.setdefault(new_name, qualifiers[old_name]); qualifiers.pop(old_name)
                definition["qualifiers"] = qualifiers
            bind.execute(templates.update().where(templates.c.id == template_id).values(definition=definition))
        changed_suggestions = []
        for suggestion_id, proposed, corrected in bind.execute(sa.select(suggestions.c.id, suggestions.c.proposed_category, suggestions.c.corrected_data)).all():
            corrected = dict(corrected or {})
            if proposed != old_name and corrected.get("category_id") != removed["id"]:
                continue
            changed_suggestions.append({"id": suggestion_id, "proposed_category": proposed, "category_id": corrected.get("category_id")})
            if corrected.get("category_id") == removed["id"]:
                corrected["category_id"] = kept["id"]
            bind.execute(suggestions.update().where(suggestions.c.id == suggestion_id).values(
                proposed_category=new_name if proposed == old_name else proposed, corrected_data=corrected))
        # Carry over what the user configured on the duplicate.
        values = {}
        if removed["shortcut"] and not kept["shortcut"]:
            values["shortcut"] = removed["shortcut"]
        elif removed["shortcut"]:
            log.warning("Shortcut %r of merged category %r dropped: %r already uses %r",
                        removed["shortcut"], old_name, new_name, kept["shortcut"])
        for field in ("pre_roll", "post_roll"):
            if kept[field] == DEFAULT_ROLL and removed[field] != DEFAULT_ROLL:
                values[field] = removed[field]
        if removed["enabled"] and not kept["enabled"]:
            values["enabled"] = True
        bind.execute(merges.insert().values(id=str(uuid.uuid4()), seq=seq, removed=removed, kept=kept,
                                            templates=changed_templates, suggestions=changed_suggestions))
        bind.execute(categories.delete().where(categories.c.id == removed["id"]))
        if values:
            bind.execute(categories.update().where(categories.c.id == kept["id"]).values(**values))
        log.info("Category %r merged into %r", old_name, new_name)


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("category_merges"):
        return  # database created fresh at this revision: nothing was merged
    for removed, kept, changed_templates, changed_suggestions in bind.execute(
            # Undo in reverse order: later merges recorded state produced by earlier ones.
            sa.select(merges.c.removed, merges.c.kept, merges.c.templates, merges.c.suggestions).order_by(merges.c.seq.desc())).all():
        if kept is None:
            bind.execute(categories.update().where(categories.c.id == removed["id"]).values(name=removed["name"]))
            continue
        # Restore the kept category's own configuration first: the shortcut may move back.
        bind.execute(categories.update().where(categories.c.id == kept["id"]).values(
            **{f: kept[f] for f in ("shortcut", "pre_roll", "post_roll", "enabled")}))
        bind.execute(categories.insert().values(**removed))
        for event_id, metadata in bind.execute(sa.select(events.c.id, events.c.metadata).where(events.c.category_id == kept["id"])).all():
            metadata = dict(metadata or {})
            if metadata.pop("merged_from", None) == removed["name"]:
                bind.execute(events.update().where(events.c.id == event_id).values(category_id=removed["id"], metadata=metadata))
        for item in changed_templates:
            definition = bind.execute(sa.select(templates.c.definition).where(templates.c.id == item["id"])).scalar()
            if definition is None:
                continue
            definition = {**definition, "categories": item["categories"]}
            if item.get("qualifiers") is not None:
                definition["qualifiers"] = item["qualifiers"]
            bind.execute(templates.update().where(templates.c.id == item["id"]).values(definition=definition))
        for item in changed_suggestions:
            corrected = bind.execute(sa.select(suggestions.c.corrected_data).where(suggestions.c.id == item["id"])).scalar()
            if corrected is None and item["category_id"] is None:
                corrected = {}
            corrected = dict(corrected or {})
            if item["category_id"] is not None:
                corrected["category_id"] = item["category_id"]
            bind.execute(suggestions.update().where(suggestions.c.id == item["id"]).values(
                proposed_category=item["proposed_category"], corrected_data=corrected))
    op.drop_table("category_merges")
