""" Regression tests: the admin API v1 must answer malformed input with a proper
    4xx status, not crash with an HTTP 500.

    - PATCH /domain/<name> on a non-existent domain built its 404 message from a
      variable that is only assigned on the next line -> UnboundLocalError -> 500.
    - POST/PATCH /user parse reply_startdate/reply_enddate by hand; a value that
      is not a valid YYYY-MM-DD raised ValueError -> 500.
"""

from mailu import models


def _bearer(app):
    return {'Authorization': f'Bearer {app.config["API_TOKEN"]}'}


def test_patch_nonexistent_domain_returns_404(app, client):
    with app.app_context():
        rv = client.patch('/api/v1/domain/nonexistent.example',
                           json={'comment': 'x'}, headers=_bearer(app))
        assert rv.status_code == 404


def _make_user(email='replytest@example.com'):
    domain = models.Domain(name=email.split('@', 1)[1])
    models.db.session.add(domain)
    user = models.User(localpart=email.split('@', 1)[0], domain_name=email.split('@', 1)[1])
    user.set_password('password')
    models.db.session.add(user)
    models.db.session.commit()
    return user


def test_patch_user_malformed_reply_startdate_returns_400(app, client):
    with app.app_context():
        user = _make_user()
        rv = client.patch(f'/api/v1/user/{user.email}',
                          json={'reply_startdate': '2022-02-30'}, headers=_bearer(app))
        assert rv.status_code == 400


def test_patch_user_nondate_reply_enddate_returns_400(app, client):
    with app.app_context():
        user = _make_user(email='replytest2@example.com')
        rv = client.patch(f'/api/v1/user/{user.email}',
                          json={'reply_enddate': 'notadate'}, headers=_bearer(app))
        assert rv.status_code == 400


def test_post_user_malformed_reply_startdate_returns_400(app, client):
    with app.app_context():
        models.db.session.add(models.Domain(name='example.com'))
        models.db.session.commit()
        rv = client.post('/api/v1/user',
                         json={'email': 'new@example.com', 'raw_password': 'Secret12!',
                               'reply_startdate': '2022-13-40'}, headers=_bearer(app))
        assert rv.status_code == 400
