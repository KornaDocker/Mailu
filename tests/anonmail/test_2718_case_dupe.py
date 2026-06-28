"""Issue #2718: creating a user/alias differing only by letter case from an
existing alias/user should be detected as a duplicate, not silently allowed.

The UI views (ui/views/users.py, ui/views/aliases.py) gate creation on
`domain.has_email(form.localpart.data)`. This test exercises that gate plus
the actual DB write to see whether a mixed-case collision is detected.
"""
from mailu import models


def _make_domain(app, name='example.com'):
    domain = models.Domain(name=name)
    models.db.session.add(domain)
    models.db.session.commit()
    return domain


def test_user_then_alias_case_differs(app):
    domain = _make_domain(app)

    # Existing USER with a capital letter in the localpart.
    user = models.User(domain=domain)
    user.localpart = 'Foo'
    user.set_password('password')
    models.db.session.add(user)
    models.db.session.commit()

    # Now an admin tries to create an alias "foo@example.com" (lowercase).
    # The UI gate is domain.has_email(localpart).
    assert domain.has_email('foo') is True, (
        "has_email did not detect the case-differing user -> duplicate slips through"
    )


def test_alias_then_user_case_differs(app):
    domain = _make_domain(app, 'example.org')

    alias = models.Alias(domain=domain)
    alias.localpart = 'Bar'
    alias.destination = ['dest@example.org']
    models.db.session.add(alias)
    models.db.session.commit()

    assert domain.has_email('bar') is True, (
        "has_email did not detect the case-differing alias -> duplicate slips through"
    )
