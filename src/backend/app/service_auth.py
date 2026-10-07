"""Service-to-service authentication for private endpoints (APP-03B).

Looks the bearer token up ONLY in `service_credentials` with the required scope. Customer
tokens live in a different table and can never authenticate here.
"""
from dataclasses import dataclass

import psycopg
from fastapi import HTTPException, Request

from app.auth import _bearer_token
from app.db import connect
from app.provision_auth import hash_token


@dataclass(frozen=True)
class ServicePrincipal:
    name: str
    scope: str


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def require_service(scope: str):
    def dependency(request: Request) -> ServicePrincipal:
        token = _bearer_token(request)
        if token is None:
            request.state.audit["result"] = "unauthenticated"
            raise _unauthenticated()
        try:
            with connect(request.app.state.settings) as conn:
                row = conn.execute(
                    "SELECT name, scope FROM service_credentials WHERE token_sha256 = %s AND scope = %s",
                    (hash_token(token), scope),
                ).fetchone()
        except psycopg.Error as exc:
            request.state.audit.update(result="error", error=type(exc).__name__)
            raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None
        if row is None:
            request.state.audit["result"] = "unauthenticated"
            raise _unauthenticated()
        request.state.audit["service"] = row[0]
        return ServicePrincipal(name=row[0], scope=row[1])
    return dependency
