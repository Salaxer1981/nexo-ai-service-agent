"""Draft schemas shared by the HTTP API and the chat agent (AGENT-01B), so both validate a ticket or lead
draft with exactly the same rules before calling the existing prepare services."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TicketDraft(BaseModel):
    """Ticket data to prepare. No customer_id: the owner always comes from authentication."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contact_name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    priority: Literal["normal", "critical"]


class LeadDraft(BaseModel):
    """REQ-API-03 lead fields only (contact channel = e-mail). No customer/session id in the body."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    need: str = Field(min_length=1, max_length=2000)
