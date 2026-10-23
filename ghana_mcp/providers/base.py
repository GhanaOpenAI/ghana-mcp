"""Base classes and data models for Ghana-MCP search providers."""
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod


@dataclass
class SearchResult:
    """Represents a unified search result from any Ghanaian data source."""
    title: str
    url: str
    snippet: str
    source: str
    category: str  # "news", "wikipedia", "academic", "public_services"
    published_date: Optional[str] = None
    score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseProvider(ABC):
    """Abstract base class for all search providers."""

    name: str = "base"
    category: str = "general"

    @abstractmethod
    def search(self, keywords: List[str], limit: int = 5) -> List[SearchResult]:
        """Search the provider using a list of keywords."""
        pass
