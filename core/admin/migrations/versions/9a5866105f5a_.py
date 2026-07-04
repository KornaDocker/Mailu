""" Lowercase existing mixed-case localparts and e-mail addresses

Revision ID: 9a5866105f5a
Revises: fdff7f84d363
Create Date: 2026-07-04 12:00:00.000000

#2695 / #2718 let users and aliases be stored with a mixed-case localpart, so
rows such as ``Foo@example.com`` and ``foo@example.com`` could coexist. The code
change in this PR lowercases localparts on write; this migration lowercases the
rows that already exist.

It mirrors the 2018 migration ``5aeb5811408e`` ("Convert all domains and emails
to lowercase") and extends it to the tables added since — ``alias.owner_email``
and ``domain_access`` (Anonymous Email Service).

Because the bug allowed case-only *duplicates*, a blind ``lower()`` would collide
on the ``user`` / ``alias`` primary key and abort the upgrade half way. We
therefore run a read-only pre-check first and abort — listing the offending
addresses — so an administrator can rename or remove one of each pair before
retrying. Auto-merging two distinct accounts is never safe, so that is
deliberately left to a human.
"""

# revision identifiers, used by Alembic.
revision = '9a5866105f5a'
down_revision = 'fdff7f84d363'

from alembic import op
import sqlalchemy as sa


# Constraint naming convention, identical to mailu.models.Base.metadata, so that
# batch_alter_table can drop and recreate the foreign keys by name on SQLite and
# PostgreSQL (same approach as migration 546b04c886f0).
naming_convention = {
    'fk': '%(table_name)s_%(column_0_name)s_fkey',
    'pk': '%(table_name)s_pkey',
}

# Lightweight table definitions, independent from the live models, limited to the
# columns this migration reads or rewrites.
_meta = sa.MetaData()
domain = sa.Table('domain', _meta, sa.Column('name', sa.String(80), primary_key=True))
relay = sa.Table('relay', _meta, sa.Column('name', sa.String(80), primary_key=True))
alternative = sa.Table('alternative', _meta,
    sa.Column('name', sa.String(80), primary_key=True),
    sa.Column('domain_name', sa.String(80)))
user = sa.Table('user', _meta,
    sa.Column('email', sa.String(255), primary_key=True),
    sa.Column('localpart', sa.String(80)),
    sa.Column('domain_name', sa.String(80)))
alias = sa.Table('alias', _meta,
    sa.Column('email', sa.String(255), primary_key=True),
    sa.Column('localpart', sa.String(80)),
    sa.Column('domain_name', sa.String(80)),
    sa.Column('owner_email', sa.String(255)))
fetch = sa.Table('fetch', _meta,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('user_email', sa.String(255)))
token = sa.Table('token', _meta,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('user_email', sa.String(255)))
manager = sa.Table('manager', _meta,
    sa.Column('domain_name', sa.String(80)),
    sa.Column('user_email', sa.String(255)))
domain_access = sa.Table('domain_access', _meta,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('domain_name', sa.String(80)),
    sa.Column('user_email', sa.String(255)))


def _lower(value):
    return value if value is None else value.lower()


def _collisions(connection, table):
    """ Map lowercased address -> sorted case variants, only for values that
        collide (i.e. more than one variant maps to the same lowercase form). """
    variants = {}
    for (value,) in connection.execute(sa.select(table.c.email)):
        variants.setdefault(value.lower(), set()).add(value)
    return {low: sorted(vals) for low, vals in variants.items() if len(vals) > 1}


def upgrade():
    connection = op.get_bind()

    # 1. Refuse to run if lowercasing would collide on a primary key (#2718).
    collisions = {}
    collisions.update(_collisions(connection, user))
    collisions.update(_collisions(connection, alias))
    if collisions:
        listing = '\n'.join(
            f'  {low}: {", ".join(vals)}' for low, vals in sorted(collisions.items())
        )
        raise RuntimeError(
            "Cannot lowercase e-mail addresses: the following case-only "
            "duplicates exist and would collide on the primary key (see #2718). "
            "Remove or rename one address of each pair, then retry the upgrade:\n"
            + listing
        )

    # 2. Drop the foreign keys that reference the primary keys we are about to
    #    rewrite (domain.name and user.email).
    with op.batch_alter_table('user', naming_convention=naming_convention) as batch:
        batch.drop_constraint('user_domain_name_fkey', type_='foreignkey')
    with op.batch_alter_table('alias', naming_convention=naming_convention) as batch:
        batch.drop_constraint('alias_domain_name_fkey', type_='foreignkey')
        batch.drop_constraint('alias_owner_email_fkey', type_='foreignkey')
    with op.batch_alter_table('alternative', naming_convention=naming_convention) as batch:
        batch.drop_constraint('alternative_domain_name_fkey', type_='foreignkey')
    with op.batch_alter_table('fetch', naming_convention=naming_convention) as batch:
        batch.drop_constraint('fetch_user_email_fkey', type_='foreignkey')
    with op.batch_alter_table('token', naming_convention=naming_convention) as batch:
        batch.drop_constraint('token_user_email_fkey', type_='foreignkey')
    with op.batch_alter_table('manager', naming_convention=naming_convention) as batch:
        batch.drop_constraint('manager_domain_name_fkey', type_='foreignkey')
        batch.drop_constraint('manager_user_email_fkey', type_='foreignkey')
    with op.batch_alter_table('domain_access', naming_convention=naming_convention) as batch:
        batch.drop_constraint('domain_access_domain_name_fkey', type_='foreignkey')
        batch.drop_constraint('domain_access_user_email_fkey', type_='foreignkey')

    # 3. Lowercase every stored name / address.
    for (name,) in connection.execute(sa.select(domain.c.name)):
        connection.execute(domain.update().where(domain.c.name == name).values(name=_lower(name)))
    for (name,) in connection.execute(sa.select(relay.c.name)):
        connection.execute(relay.update().where(relay.c.name == name).values(name=_lower(name)))
    for row in connection.execute(alternative.select()):
        connection.execute(alternative.update().where(alternative.c.name == row.name).values(
            name=_lower(row.name), domain_name=_lower(row.domain_name)))
    for row in connection.execute(user.select()):
        connection.execute(user.update().where(user.c.email == row.email).values(
            email=_lower(row.email), localpart=_lower(row.localpart), domain_name=_lower(row.domain_name)))
    for row in connection.execute(alias.select()):
        connection.execute(alias.update().where(alias.c.email == row.email).values(
            email=_lower(row.email), localpart=_lower(row.localpart),
            domain_name=_lower(row.domain_name), owner_email=_lower(row.owner_email)))
    for row in connection.execute(fetch.select()):
        connection.execute(fetch.update().where(fetch.c.id == row.id).values(user_email=_lower(row.user_email)))
    for row in connection.execute(token.select()):
        connection.execute(token.update().where(token.c.id == row.id).values(user_email=_lower(row.user_email)))
    for row in connection.execute(manager.select()):
        connection.execute(manager.update().where(sa.and_(
            manager.c.domain_name == row.domain_name,
            manager.c.user_email == row.user_email,
        )).values(domain_name=_lower(row.domain_name), user_email=_lower(row.user_email)))
    for row in connection.execute(domain_access.select()):
        connection.execute(domain_access.update().where(domain_access.c.id == row.id).values(
            domain_name=_lower(row.domain_name), user_email=_lower(row.user_email)))

    # 4. Restore the foreign keys.
    with op.batch_alter_table('user', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('user_domain_name_fkey', 'domain', ['domain_name'], ['name'])
    with op.batch_alter_table('alias', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('alias_domain_name_fkey', 'domain', ['domain_name'], ['name'])
        batch.create_foreign_key('alias_owner_email_fkey', 'user', ['owner_email'], ['email'])
    with op.batch_alter_table('alternative', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('alternative_domain_name_fkey', 'domain', ['domain_name'], ['name'])
    with op.batch_alter_table('fetch', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('fetch_user_email_fkey', 'user', ['user_email'], ['email'])
    with op.batch_alter_table('token', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('token_user_email_fkey', 'user', ['user_email'], ['email'])
    with op.batch_alter_table('manager', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('manager_domain_name_fkey', 'domain', ['domain_name'], ['name'])
        batch.create_foreign_key('manager_user_email_fkey', 'user', ['user_email'], ['email'])
    with op.batch_alter_table('domain_access', naming_convention=naming_convention) as batch:
        batch.create_foreign_key('domain_access_domain_name_fkey', 'domain', ['domain_name'], ['name'])
        batch.create_foreign_key('domain_access_user_email_fkey', 'user', ['user_email'], ['email'])


def downgrade():
    # Lowercasing is a one-way normalisation (the original case is lost).
    pass
