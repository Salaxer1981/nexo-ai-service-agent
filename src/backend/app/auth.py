"""Resolve the authenticated customer from the Authorization header.

The customer identity comes ONLY from a server-side lookup of the bearer token.
customer_id values in query strings, headers, bodies or chat text are never read
here and can never override this identity (INV-01).
"""
from dataclasses import dataclass

import psycopg
from fastapi import HTTPException, Request

from app.db import connect
from app.provision_auth import hash_token


@dataclass(frozen=True)
class AuthenticatedCustomer:
    customer_id: str
    display_name: str


def _unauthenticated() -> HTTPException:
    # Same response for missing, malformed and unknown tokens: nothing to probe.
    return HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def require_customer(request: Request) -> AuthenticatedCustomer:
    token = _bearer_token(request)
    if token is None:
        request.state.audit["result"] = "unauthenticated"
        raise _unauthenticated()
    try:
        with connect(request.app.state.settings) as conn:
            row = conn.execute(
                "SELECT c.id, c.display_name FROM api_credentials k"
                " JOIN customers c ON c.id = k.customer_id"
                " WHERE k.token_sha256 = %s",
                (hash_token(token),),
            ).fetchone()
    except psycopg.Error as exc:
        request.state.audit.update(result="error", error=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None
    if row is None:
        request.state.audit["result"] = "unauthenticated"
        raise _unauthenticated()
    customer = AuthenticatedCustomer(customer_id=row[0], display_name=row[1])
    request.state.audit["customer_id"] = customer.customer_id
    return customer
