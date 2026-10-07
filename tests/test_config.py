import pytest
from fastapi.testclient import TestClient

from app.config import REQUIRED_VARS, ConfigError, load_settings
from app.main import app
from conftest import TEST_ENV


def test_loads_settings_from_environment():
    settings = load_settings(TEST_ENV)
    assert settings.postgres_host == "db"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "nexo_test"


def test_port_defaults_to_5432():
    env = {k: v for k, v in TEST_ENV.items() if k != "POSTGRES_PORT"}
    assert load_settings(env).postgres_port == 5432


@pytest.mark.parametrize("missing", REQUIRED_VARS)
def test_missing_required_variable_fails_with_name_only(missing):
    env = {k: v for k, v in TEST_ENV.items() if k != missing}
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert missing in str(exc.value)
    assert TEST_ENV["POSTGRES_PASSWORD"] not in str(exc.value)


@pytest.mark.parametrize("bad_port", ["abc", "0", "70000"])
def test_invalid_port_is_rejected(bad_port):
    with pytest.raises(ConfigError):
        load_settings({**TEST_ENV, "POSTGRES_PORT": bad_port})


def test_password_is_not_exposed_in_repr():
    settings = load_settings(TEST_ENV)
    assert TEST_ENV["POSTGRES_PASSWORD"] not in repr(settings)
    assert TEST_ENV["POSTGRES_PASSWORD"] not in str(settings)


def test_app_refuses_to_start_without_configuration(monkeypatch):
    for name in REQUIRED_VARS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigError):
        with TestClient(app):
            pass
