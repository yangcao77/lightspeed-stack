"""Model for conversation history cache entry."""

from pydantic import BaseModel


class CacheEntry(BaseModel):
    """Model representing a cache entry.

    Attributes:
        query: The query string
        response: The response string
        provider: Provider identification
        model: Model identification
    """

    query: str
    response: str
    provider: str
    model: str
