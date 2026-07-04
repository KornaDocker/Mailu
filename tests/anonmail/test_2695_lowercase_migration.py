""" Regression test for the #2695 / #2718 lowercase migration (9a5866105f5a).

The migration lowercases every stored name / e-mail address across all tables,
and aborts cleanly if lowercasing would collide on a primary key (the case-only
duplicates the bug allowed). Both paths are exercised here against a real Mailu
schema on SQLite, driving the migration through Alembic's batch operations.
"""

import importlib.util
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from mailu import models

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / 'core' / 'admin' / 'migrations' / 'versions' / '9a5866105f5a_.py'
)


def _load_migration():
    spec = importlib.util.spec_from_file_location('mig_2695', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(engine):
    """ Drive the migration's upgrade() against a fresh connection, binding its
        `op` proxy to that connection (as Alembic does during a real run). """
    mig = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        mig.op = Operations(ctx)
        with conn.begin():
            mig.upgrade()


def _sql(engine, statement):
    with engine.connect() as conn:
        return list(conn.exec_driver_sql(statement))


def _mutate_to_mixed_case(engine, statements):
    """ Force mixed-case values straight into the DB (bypassing the column type's
        bind processing and foreign-key enforcement), simulating the bug state. """
    with engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA foreign_keys=OFF')
        for statement in statements:
            conn.exec_driver_sql(statement)


def _seed_consistent_lowercase(app):
    """ Create a consistent, all-lowercase object graph via the ORM (so every
        NOT NULL default is filled), touching every table the migration rewrites. """
    db = models.db
    domain = models.Domain(name='example.com')
    db.session.add(domain)

    user = models.User()
    user.email = 'foo@example.com'
    user.password = 'x'
    db.session.add(user)

    alias = models.Alias()
    alias.email = 'bar@example.com'
    alias.destination = ['foo@example.com']
    alias.owner_email = 'foo@example.com'
    db.session.add(alias)

    db.session.add(models.Alternative(name='alt.example.com', domain_name='example.com'))
    db.session.add(models.Relay(name='relay.net'))
    db.session.add(models.Token(user_email='foo@example.com', password='x'))
    db.session.add(models.Fetch(
        user_email='foo@example.com', protocol='imap', host='host.example',
        port=993, tls=True, username='remote', password='x'))
    db.session.add(models.DomainAccess(domain_name='example.com', user_email='foo@example.com'))
    domain.managers.append(user)
    db.session.commit()


def test_migration_lowercases_every_table(app):
    engine = models.db.engine
    _seed_consistent_lowercase(app)

    _mutate_to_mixed_case(engine, [
        "UPDATE domain SET name='Example.COM'",
        "UPDATE relay SET name='Relay.NET'",
        "UPDATE alternative SET name='Alt.Example.COM', domain_name='Example.COM'",
        "UPDATE \"user\" SET email='Foo@Example.COM', localpart='Foo', domain_name='Example.COM'",
        "UPDATE alias SET email='Bar@Example.COM', localpart='Bar', domain_name='Example.COM', owner_email='Foo@Example.COM'",
        "UPDATE fetch SET user_email='Foo@Example.COM'",
        "UPDATE token SET user_email='Foo@Example.COM'",
        "UPDATE manager SET domain_name='Example.COM', user_email='Foo@Example.COM'",
        "UPDATE domain_access SET domain_name='Example.COM', user_email='Foo@Example.COM'",
    ])

    _run_upgrade(engine)

    # Every stored value is lowercased ...
    assert _sql(engine, "SELECT name FROM domain") == [('example.com',)]
    assert _sql(engine, "SELECT name FROM relay") == [('relay.net',)]
    assert _sql(engine, "SELECT name, domain_name FROM alternative") == [('alt.example.com', 'example.com')]
    assert _sql(engine, "SELECT email, localpart, domain_name FROM \"user\"") == [('foo@example.com', 'foo', 'example.com')]
    assert _sql(engine, "SELECT email, localpart, domain_name, owner_email FROM alias") == [
        ('bar@example.com', 'bar', 'example.com', 'foo@example.com')]
    assert _sql(engine, "SELECT user_email FROM fetch") == [('foo@example.com',)]
    assert _sql(engine, "SELECT user_email FROM token") == [('foo@example.com',)]
    assert _sql(engine, "SELECT domain_name, user_email FROM manager") == [('example.com', 'foo@example.com')]
    assert _sql(engine, "SELECT domain_name, user_email FROM domain_access") == [('example.com', 'foo@example.com')]

    # ... and referential integrity is intact (foreign keys were restored).
    # `foreign_key_check` reports violations regardless of enforcement, so it does
    # not mutate the shared connection's PRAGMA state.
    assert _sql(engine, 'PRAGMA foreign_key_check') == []


def test_migration_aborts_on_case_only_duplicate(app):
    engine = models.db.engine
    db = models.db
    db.session.add(models.Domain(name='example.com'))
    for localpart in ('foo', 'foofoo'):
        user = models.User()
        user.email = f'{localpart}@example.com'
        user.password = 'x'
        db.session.add(user)
    db.session.commit()

    # Turn the second user into a case-only duplicate of the first.
    _mutate_to_mixed_case(engine, [
        "UPDATE \"user\" SET email='Foo@example.com', localpart='Foo' WHERE email='foofoo@example.com'",
    ])

    with pytest.raises(RuntimeError) as excinfo:
        _run_upgrade(engine)

    message = str(excinfo.value)
    assert 'foo@example.com' in message
    assert 'Foo@example.com' in message

    # Nothing was changed: both variants still present.
    emails = {row[0] for row in _sql(engine, "SELECT email FROM \"user\"")}
    assert emails == {'foo@example.com', 'Foo@example.com'}
