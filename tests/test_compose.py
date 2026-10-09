"""Static validation of compose.yaml and the backend Dockerfile.

Runtime validation (`docker compose config`, `up`, healthchecks) needs a Docker host.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
PG_DATA_DIR = "/var/lib/postgresql/data"
SECRET_VARS = ("POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_DB", "AUTH_TOKEN_CUSTOMER_A", "AUTH_TOKEN_CUSTOMER_B",
               "N8N_ENCRYPTION_KEY", "LEAD_WRITER_TOKEN_SHA256")


def _is_pinned(image: str) -> bool:
    name, _, tag = image.rpartition(":")
    return bool(name) and "/" not in tag and tag not in ("", "latest")


def test_compose_parses_with_expected_services():
    assert set(SERVICES) == {"backend", "db", "n8n", "web"}


def test_db_publishes_no_host_port():
    db = SERVICES["db"]
    assert "ports" not in db
    assert db.get("network_mode") != "host"


def test_all_published_ports_bind_to_loopback():
    for name, service in SERVICES.items():
        for mapping in service.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), f"{name} publishes {mapping} beyond loopback"


@pytest.mark.parametrize("service", ["db", "backend", "n8n"])
def test_compose_images_are_pinned(service):
    image = SERVICES[service]["image"]
    assert _is_pinned(image), f"{service} image not pinned: {image}"


def test_dockerfile_base_image_is_pinned():
    dockerfile = (ROOT / "src" / "backend" / "Dockerfile").read_text(encoding="utf-8")
    bases = re.findall(r"^FROM\s+(\S+)", dockerfile, flags=re.MULTILINE)
    assert bases, "Dockerfile has no FROM line"
    for base in bases:
        assert _is_pinned(base), f"Dockerfile base image not pinned: {base}"


def test_db_uses_named_persistent_volume():
    assert "db_data" in COMPOSE["volumes"]
    assert f"db_data:{PG_DATA_DIR}" in SERVICES["db"]["volumes"]


def test_db_has_healthcheck_and_backend_waits_for_it():
    assert "pg_isready" in " ".join(SERVICES["db"]["healthcheck"]["test"])
    assert SERVICES["backend"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_restart_policy_set():
    for name, service in SERVICES.items():
        assert service.get("restart") == "unless-stopped", name


def test_backend_receives_synthetic_auth_tokens_via_substitution():
    env = SERVICES["backend"]["environment"]
    assert {"AUTH_TOKEN_CUSTOMER_A", "AUTH_TOKEN_CUSTOMER_B"} <= set(env)
    assert "AUTH_TOKEN_CUSTOMER_A" not in SERVICES["db"].get("environment", {})


def test_container_migrates_before_serving():
    dockerfile = (ROOT / "src" / "backend" / "Dockerfile").read_text(encoding="utf-8")
    cmd = re.search(r"^CMD (.+)$", dockerfile, flags=re.MULTILINE).group(1)
    assert cmd.index("app.migrate") < cmd.index("app.provision_auth") < cmd.index("uvicorn")
    assert "/health/ready" in dockerfile


def test_credentials_come_only_from_variable_substitution():
    for name, service in SERVICES.items():
        env = service.get("environment", {})
        for var in SECRET_VARS:
            if var in env:
                assert re.fullmatch(r"\$\{" + var + r":\?[^}]*\}", env[var]), f"{name}.{var} is not ${{{var}:?...}}"


# --- N8N-01: self-hosted n8n foundation ----------------------------------------------

def test_n8n_uses_official_pinned_image():
    assert re.fullmatch(r"n8nio/n8n:\d+\.\d+\.\d+", SERVICES["n8n"]["image"])


def test_n8n_ui_published_on_loopback_only():
    assert SERVICES["n8n"]["ports"] == ["127.0.0.1:${N8N_HOST_PORT:-5678}:5678"]


def test_networks_follow_least_privilege():
    assert SERVICES["db"]["networks"] == ["internal"]
    assert sorted(SERVICES["backend"]["networks"]) == ["automation", "internal", "web"]
    assert SERVICES["n8n"]["networks"] == ["automation"]  # n8n can reach the backend, never the DB
    assert SERVICES["web"]["networks"] == ["web"]  # UI-02: the web client reaches only the backend, never db or n8n
    assert set(COMPOSE["networks"]) == {"internal", "automation", "web"}
    for name, net in COMPOSE["networks"].items():
        assert not (net or {}).get("internal"), f"{name}: internal:true would block future egress"


def test_n8n_state_is_on_a_named_volume():
    assert "n8n_data" in COMPOSE["volumes"]
    assert SERVICES["n8n"]["volumes"] == ["n8n_data:/home/node/.n8n"]


def test_n8n_has_healthcheck_and_minimal_telemetry():
    assert "/healthz" in " ".join(SERVICES["n8n"]["healthcheck"]["test"])
    env = SERVICES["n8n"]["environment"]
    assert env["N8N_DIAGNOSTICS_ENABLED"] == "false"
    assert env["N8N_VERSION_NOTIFICATIONS_ENABLED"] == "false"


def test_n8n_gets_no_application_secrets():
    env = SERVICES["n8n"]["environment"]
    assert not {k for k in env if k.startswith(("POSTGRES_", "AUTH_TOKEN_"))}
    assert "depends_on" not in SERVICES["n8n"]


@pytest.mark.parametrize("service", ["db", "backend", "n8n"])
def test_no_privileged_containers_or_docker_socket(service):
    svc = SERVICES[service]
    assert not svc.get("privileged")
    assert not any("docker.sock" in str(v) for v in svc.get("volumes", []))
    assert svc.get("network_mode") != "host"


def test_env_example_has_names_only():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            assert value in ("", "https://openrouter.ai/api/v1"), f"{name} has a value in .env.example"
    assert "N8N_ENCRYPTION_KEY=" in example and "N8N_HOST_PORT=" in example


# --- APP-03B: lead workflow wiring --------------------------------------------------------

def test_backend_gets_only_the_hash_of_the_lead_writer_token():
    env = SERVICES["backend"]["environment"]
    assert env["LEAD_WRITER_TOKEN_SHA256"] == "${LEAD_WRITER_TOKEN_SHA256:?LEAD_WRITER_TOKEN_SHA256 is required}"
    assert not [k for k in env if k.startswith("LEAD_WRITER") and k != "LEAD_WRITER_TOKEN_SHA256"]
    assert env["N8N_LEAD_WEBHOOK_URL"] == "http://n8n:5678/webhook/nexo-lead-create"


def test_n8n_receives_no_lead_writer_material_via_env():
    # The raw token lives only in n8n's encrypted credential store (imported at deployment).
    assert not [k for k in SERVICES["n8n"]["environment"] if "LEAD" in k or "TOKEN" in k]


# --- RAG-01 ------------------------------------------------------------------------------

def test_backend_mounts_knowledge_read_only_and_rag_key_is_optional():
    backend = SERVICES["backend"]
    assert "./knowledge:/srv/knowledge:ro" in backend["volumes"]
    env = backend["environment"]
    assert env["OPENROUTER_API_KEY"] == "${OPENROUTER_API_KEY:-}"  # optional: never a literal, never required
    assert env["RAG_KNOWLEDGE_DIR"] == "/srv/knowledge"
    assert not [k for k in SERVICES["n8n"]["environment"] if "OPENROUTER" in k]
    assert not [k for k in SERVICES["db"]["environment"] if "OPENROUTER" in k]


def test_backend_chat_model_is_configurable_with_the_verified_default():
    env = SERVICES["backend"]["environment"]
    assert env["OPENROUTER_CHAT_MODEL"] == "${OPENROUTER_CHAT_MODEL:-x-ai/grok-4.7}"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "\nOPENROUTER_CHAT_MODEL=\n" in example and "\nOPENROUTER_MODEL=" not in example


# UI-02: the evaluation web client is the browser's only credential boundary.
def test_web_is_loopback_only_hardened_and_receives_only_demo_credentials():
    web = SERVICES["web"]
    assert web["ports"] == ["127.0.0.1:${WEB_PORT:-8080}:8080"]
    assert web["read_only"] is True and web["cap_drop"] == ["ALL"] and "no-new-privileges:true" in web["security_opt"]
    assert set(web["environment"]) == {"BACKEND_URL", "AUTH_TOKEN_CUSTOMER_A", "AUTH_TOKEN_CUSTOMER_B"}
    assert web["environment"]["BACKEND_URL"] == "http://backend:8000"
    assert web["depends_on"]["backend"]["condition"] == "service_healthy"
    assert web["build"] == "./src/frontend"  # a plain path: no build args can carry credentials
    assert not [k for k in web["environment"] if k.startswith(("POSTGRES_", "OPENROUTER", "N8N_", "LEAD_WRITER", "VITE_"))]


def test_web_dockerfile_base_is_pinned_and_runs_unprivileged():
    dockerfile = (ROOT / "src" / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    bases = re.findall(r"^FROM\s+(\S+)", dockerfile, flags=re.M)
    assert bases and all(_is_pinned(b) for b in bases), bases
    assert re.search(r"^USER node$", dockerfile, flags=re.M)
    assert "ARG " not in dockerfile  # no build-time arguments at all


# --- P0.4F: web search configuration wiring (backend only, OFF by default) ---------------------

WEB_VARS = ("WEB_SEARCH_ENABLED", "WEB_SEARCH_ENGINE", "WEB_SEARCH_MAX_RESULTS", "WEB_SEARCH_TIMEOUT_SECONDS")
_SUBST = re.compile(r"\$\$|\$\{(\w+)(?:(:?[-?])([^}]*))?\}")


def _interpolate(value, env: dict) -> str:
    """Compose variable substitution (`${V}`, `${V:-d}`, `${V-d}`, `${V:?m}`, `${V?m}`, `$$`); unknown forms fail."""
    def sub(m):
        if m.group(0) == "$$":
            return "$"
        name, op, arg = m.groups()
        set_, nonempty = name in env, bool(env.get(name))
        if op is None:
            return env.get(name, "")
        if op in (":-", "-"):
            return env[name] if (nonempty if op == ":-" else set_) else arg
        if not (nonempty if op == ":?" else set_):
            raise KeyError(f"{name}: {arg}")
        return env[name]
    out = _SUBST.sub(sub, str(value))
    assert "${" not in out, f"unsupported substitution in {value!r}"
    return out


def _required_env() -> dict:
    return {"POSTGRES_DB": "nexo", "POSTGRES_USER": "nexo", "POSTGRES_PASSWORD": "x" * 32,
            "AUTH_TOKEN_CUSTOMER_A": "a" * 32, "AUTH_TOKEN_CUSTOMER_B": "b" * 32,
            "LEAD_WRITER_TOKEN_SHA256": "0" * 64, "N8N_ENCRYPTION_KEY": "k" * 32}


def _service_env(service: str, env: dict) -> dict:
    return {k: _interpolate(v, env) for k, v in SERVICES[service].get("environment", {}).items()}


def test_backend_receives_web_search_vars_with_safe_defaults():
    env = SERVICES["backend"]["environment"]
    assert {k: env[k] for k in WEB_VARS} == {
        "WEB_SEARCH_ENABLED": "${WEB_SEARCH_ENABLED:-false}",
        "WEB_SEARCH_ENGINE": "${WEB_SEARCH_ENGINE:-exa}",
        "WEB_SEARCH_MAX_RESULTS": "${WEB_SEARCH_MAX_RESULTS:-3}",
        "WEB_SEARCH_TIMEOUT_SECONDS": "${WEB_SEARCH_TIMEOUT_SECONDS:-45}"}


@pytest.mark.parametrize("dotenv", [{}, {k: "" for k in WEB_VARS}], ids=["absent", "empty"])
def test_web_search_defaults_reach_the_backend_disabled(dotenv):
    from app.config import load_settings
    from app.llm import chat_client_from_settings
    env = _service_env("backend", {**_required_env(), **dotenv, "OPENROUTER_API_KEY": "sk-test"})
    assert {k: env[k] for k in WEB_VARS} == {"WEB_SEARCH_ENABLED": "false", "WEB_SEARCH_ENGINE": "exa",
                                             "WEB_SEARCH_MAX_RESULTS": "3", "WEB_SEARCH_TIMEOUT_SECONDS": "45"}
    s = load_settings(env)
    assert (s.web_search_enabled, s.web_search_engine, s.web_search_max_results, s.web_search_timeout_seconds) == \
        (False, "exa", 3, 45.0)
    assert chat_client_from_settings(s).web_search is None  # disabled: no external search is ever requested


def test_web_search_enabled_in_dotenv_reaches_the_backend():
    from app.config import load_settings
    from app.llm import WebSearchConfig, chat_client_from_settings
    env = _service_env("backend", {**_required_env(), "OPENROUTER_API_KEY": "sk-test", "WEB_SEARCH_ENABLED": "true",
                                   "WEB_SEARCH_ENGINE": "exa", "WEB_SEARCH_MAX_RESULTS": "3",
                                   "WEB_SEARCH_TIMEOUT_SECONDS": "45"})
    assert env["WEB_SEARCH_ENABLED"] == "true"
    assert chat_client_from_settings(load_settings(env)).web_search == WebSearchConfig("exa", 3, 45.0)


def test_web_search_vars_reach_no_other_service():
    for name in ("db", "n8n", "web"):
        svc = SERVICES[name]
        assert not [k for k in svc.get("environment", {}) if k.startswith("WEB_SEARCH")], name
        assert "WEB_SEARCH" not in str(svc.get("build", "")) and "WEB_SEARCH" not in str(svc.get("env_file", "")), name
    assert "env_file" not in SERVICES["backend"]  # explicit allow-list only: the .env is never passed wholesale
    for path in ("src/frontend/Dockerfile", "src/frontend/server/server.mjs"):
        assert "WEB_SEARCH" not in (ROOT / path).read_text(encoding="utf-8"), path


def test_web_search_vars_are_optional_and_carry_no_secret():
    env = SERVICES["backend"]["environment"]
    for k in WEB_VARS:
        assert re.fullmatch(r"\$\{" + k + r":-[a-z0-9]+\}", env[k]), k  # optional with a plain default; never required
        assert not any(w in k for w in ("KEY", "TOKEN", "PASSWORD", "SECRET"))
    assert env["OPENROUTER_API_KEY"] == "${OPENROUTER_API_KEY:-}"  # web search reuses the existing key: no new secret


def test_whole_compose_interpolates_with_only_the_required_vars():
    # Static stand-in for `docker compose config` (no Docker host here): every substitution uses a supported form,
    # an .env without any WEB_SEARCH_* line still renders, and a missing required var still fails.
    for name in SERVICES:
        _service_env(name, _required_env())
        for mapping in SERVICES[name].get("ports", []):
            _interpolate(mapping, _required_env())
    with pytest.raises(KeyError):
        _service_env("backend", {k: v for k, v in _required_env().items() if k != "POSTGRES_PASSWORD"})
