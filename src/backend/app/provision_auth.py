"""Provision the SYNTHETIC assessment credentials.

Reads one token per synthetic customer from the environment and stores only its
SHA-256 hash. This is deliberately simple assessment authentication, not a
production identity platform (no expiry, no rotation policy, no user accounts).

Usage: python -m app.provision_auth
"""
import hashlib
import os
import re
import sys

import psycopg

from app.config import ConfigError, load_settings
from app.db import connect

# Environment variable -> synthetic customer it authenticates. Server-side only.
TOKEN_ENV_TO_CUSTOMER = {
    "AUTH_TOKEN_CUSTOMER_A": "CUSTOMER_A",
    "AUTH_TOKEN_CUSTOMER_B": "CUSTOMER_B",
}
CREDENTIAL_LABEL = "assessment-synthetic"
MIN_TOKEN_LENGTH = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def read_tokens(environ=None) -> dict[str, str]:
    """Return {customer_id: raw_token}. Errors name variables, never values."""
    env = os.environ if environ is None else environ
    tokens = {}
    for var, customer_id in TOKEN_ENV_TO_CUSTOMER.items():
        token = env.get(var, "")
        if len(token) < MIN_TOKEN_LENGTH:
            raise ConfigError(f"{var} must be set to a random value of at least {MIN_TOKEN_LENGTH} characters")
        tokens[customer_id] = token
    if len(set(tokens.values())) != len(tokens):
        raise ConfigError("Each AUTH_TOKEN_CUSTOMER_* variable must have a distinct value")
    return tokens


def provision(conn: psycopg.Connection, tokens: dict[str, str]) -> list[str]:
    with conn.transaction():
        for customer_id, token in tokens.items():
            conn.execute(
                "INSERT INTO api_credentials (customer_id, label, token_sha256) VALUES (%s, %s, %s)"
                " ON CONFLICT (customer_id, label) DO UPDATE SET token_sha256 = EXCLUDED.token_sha256",
                (customer_id, CREDENTIAL_LABEL, hash_token(token)),
            )
    return sorted(tokens)


# Machine credentials (APP-03B). The backend receives ONLY the SHA-256 of the token; the raw token
# lives solely in n8n's encrypted credential store, so the backend itself cannot impersonate n8n.
SERVICE_HASH_ENV = {"LEAD_WRITER_TOKEN_SHA256": ("n8n-lead-writer", "lead_write")}
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def read_service_hashes(environ=None, customer_tokens: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    """Return {name: (scope, token_sha256)}. Errors name variables, never values."""
    env = os.environ if environ is None else environ
    result = {}
    for var, (name, scope) in SERVICE_HASH_ENV.items():
        value = env.get(var, "").strip().lower()
        if not _SHA256_HEX.fullmatch(value):
            raise ConfigError(f"{var} must be the 64-hex-character SHA-256 of a random service token")
        if customer_tokens and value in {hash_token(t) for t in customer_tokens.values()}:
            raise ConfigError(f"{var} must not be derived from a customer token")
        result[name] = (scope, value)
    return result


def provision_services(conn: psycopg.Connection, services: dict[str, tuple[str, str]]) -> list[str]:
    with conn.transaction():
        for name, (scope, digest) in services.items():
            conn.execute(
                "INSERT INTO service_credentials (name, scope, token_sha256) VALUES (%s, %s, %s)"
                " ON CONFLICT (name) DO UPDATE SET scope = EXCLUDED.scope, token_sha256 = EXCLUDED.token_sha256",
                (name, scope, digest),
            )
    return sorted(services)


def main() -> int:
    tokens = read_tokens()
    services = read_service_hashes(customer_tokens=tokens)
    with connect(load_settings()) as conn:
        customers = provision(conn, tokens)
        names = provision_services(conn, services)
    print(f"synthetic credentials provisioned for: {', '.join(customers)}")
    print(f"service credentials provisioned: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
