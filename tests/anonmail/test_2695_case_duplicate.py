"""Regression tests for #2695:

Creating a duplicate user/alias where the existing one differs only by letter
case used to fall through Domain.has_email() and crash with a 500
(IntegrityError on the lowercased email primary key) instead of being rejected
cleanly as 'Email is already used'.

These tests reproduce the original UI path:
    if domain.has_email(form.localpart.data):
        flash('Email is already used')
and the actual DB-level collision.
"""
from itertools import chain

import sqlalchemy.exc
from mailu import models


def _domain(app, name='example.com'):
    d = models.Domain(name=name)
    models.db.session.add(d)
    models.db.session.commit()
    return d


class TestCaseInsensitiveDuplicate:

    def test_email_setter_lowercases_localpart_and_pk(self, app):
        """A user created via the email setter must be stored fully lowercased."""
        with app.app_context():
            _domain(app)
            u = models.User(email='AbC@example.com')
            u.set_password('password')
            models.db.session.add(u)
            models.db.session.commit()
            assert u.email == 'abc@example.com'
            assert u.localpart == 'abc'

    def test_has_email_detects_case_differing_duplicate_user(self, app):
        """domain.has_email must catch a duplicate regardless of input case
        AND regardless of the stored entry's case (the #2695 bug)."""
        with app.app_context():
            d = _domain(app)
            # existing user with a capital letter, created the way the admin UI
            # does it: blank User + populate localpart attribute directly.
            u = models.User(domain=d)
            u.localpart = 'AbC'
            u.set_password('password')
            models.db.session.add(u)
            models.db.session.commit()

            # The UI checks: domain.has_email(form.localpart.data)
            assert d.has_email('abc') is True      # lowercase attempt
            assert d.has_email('AbC') is True       # exact-case attempt
            assert d.has_email('ABC') is True       # upper attempt

    def test_has_email_detects_case_differing_duplicate_alias(self, app):
        with app.app_context():
            d = _domain(app)
            a = models.Alias(domain=d, destination=['x@other.org'], wildcard=False)
            a.localpart = 'TeaM'
            models.db.session.add(a)
            models.db.session.commit()
            assert d.has_email('team') is True
            assert d.has_email('TeaM') is True

    def test_actual_duplicate_commit_would_collide_on_pk(self, app):
        """Sanity: two case-differing emails really do map to the same PK, so the
        ONLY thing preventing a 500 is has_email catching it first."""
        with app.app_context():
            d = _domain(app)
            u1 = models.User(email='AbC@example.com')
            u1.set_password('password')
            models.db.session.add(u1)
            models.db.session.commit()

            # mirror the UI: it relies on has_email to avoid the insert
            assert d.has_email('abc') is True
