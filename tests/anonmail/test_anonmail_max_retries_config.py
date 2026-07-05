""" Regression test: ANONMAIL_MAX_RETRIES is read from the environment as a raw
    string but used numerically (range(...), comparisons). Without an int()
    coercion, overriding it via the environment made anonymous-alias creation
    raise `TypeError: 'str' object cannot be interpreted as an integer`.
"""

from mailu import configuration, create_app_from_config


def test_anonmail_max_retries_env_override_coerced_to_int(env_setup, monkeypatch):
    monkeypatch.setenv('ANONMAIL_MAX_RETRIES', '20')
    config = configuration.ConfigManager()
    app = create_app_from_config(config)
    assert app.config['ANONMAIL_MAX_RETRIES'] == 20
    assert isinstance(app.config['ANONMAIL_MAX_RETRIES'], int)
