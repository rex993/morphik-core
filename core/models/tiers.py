from enum import Enum
from typing import Any, Dict


class AccountTier(str, Enum):
    """Available account tiers."""

    FREE = "free"
    PRO = "pro"
    TEAMS = "teams"
    SELF_HOSTED = "self_hosted"


# Tier limits definition - organized by API endpoint usage
TIER_LIMITS = {
    AccountTier.FREE: {
        # Application limits
        "app_limit": 1,  # Maximum number of applications
        # Storage limits
        "storage_file_limit": 30,  # Maximum number of files in storage
        "storage_size_limit_gb": 0.25,  # Maximum storage size in GB
        "hourly_ingest_limit": 30,  # Maximum file/text ingests per hour
        "monthly_ingest_limit": 30,  # Maximum file/text ingests per month
        # Query limits
        "hourly_query_limit": 30,  # Maximum queries per hour
        "monthly_query_limit": 50,  # Maximum queries per month
        # Graph limits
        "graph_creation_limit": 1,  # Maximum number of graphs
        "hourly_graph_query_limit": 1,  # Maximum graph queries per hour
        "monthly_graph_query_limit": 1,  # Maximum graph queries per month
        # Cache limits
        "cache_creation_limit": 0,  # Maximum number of caches
        "hourly_cache_query_limit": 0,  # Maximum cache queries per hour
        "monthly_cache_query_limit": 0,  # Maximum cache queries per month
        # Agent call limits
        "hourly_agent_limit": 5,
        "monthly_agent_limit": 5,
    },
    AccountTier.PRO: {
        # Application limits
        "app_limit": 5,  # Maximum number of applications
        # Storage limits
        "storage_file_limit": 1000,  # Maximum number of files in storage
        "storage_size_limit_gb": 10,  # Maximum storage size in GB
        "hourly_ingest_limit": 100,  # Maximum file/text ingests per hour
        "monthly_ingest_limit": 3000,  # Maximum file/text ingests per month
        # Query limits
        "hourly_query_limit": 100,  # Maximum queries per hour
        "monthly_query_limit": 10000,  # Maximum queries per month
        # Graph limits
        "graph_creation_limit": 10,  # Maximum number of graphs
        "hourly_graph_query_limit": 50,  # Maximum graph queries per hour
        "monthly_graph_query_limit": 1000,  # Maximum graph queries per month
        # Cache limits
        "cache_creation_limit": 5,  # Maximum number of caches
        "hourly_cache_query_limit": 200,  # Maximum cache queries per hour
        "monthly_cache_query_limit": 5000,  # Maximum cache queries per month
        # Agent call limits for PRO (unlimited)
        "hourly_agent_limit": 100,
        "monthly_agent_limit": 1000,
    },
    AccountTier.TEAMS: {
        # Teams tier – generous limits but still bounded
        # Application limits
        "app_limit": 100,  # Maximum number of applications
        # Storage limits
        "storage_file_limit": 500000,  # Maximum number of files in storage
        "storage_size_limit_gb": 50,  # Maximum storage size in GB
        "hourly_ingest_limit": 500,  # Maximum file/text ingests per hour
        "monthly_ingest_limit": 15000,  # Maximum file/text ingests per month
        # Query limits
        "hourly_query_limit": 500,  # Maximum queries per hour
        "monthly_query_limit": 50000,  # Maximum queries per month
        # Graph limits
        "graph_creation_limit": 50,  # Maximum number of graphs
        "hourly_graph_query_limit": 200,  # Maximum graph queries per hour
        "monthly_graph_query_limit": 10000,  # Maximum graph queries per month
        # Cache limits
        "cache_creation_limit": 20,  # Maximum number of caches
        "hourly_cache_query_limit": 1000,  # Maximum cache queries per hour
        "monthly_cache_query_limit": 50000,  # Maximum cache queries per month
        # Agent call limits
        "hourly_agent_limit": 500,
        "monthly_agent_limit": 10000,
    },
    AccountTier.SELF_HOSTED: {
        # Self-hosted has no limits
        # Application limits
        "app_limit": float("inf"),  # Maximum number of applications
        # Storage limits
        "storage_file_limit": float("inf"),  # Maximum number of files in storage
        "storage_size_limit_gb": float("inf"),  # Maximum storage size in GB
        "hourly_ingest_limit": float("inf"),  # Maximum file/text ingests per hour
        "monthly_ingest_limit": float("inf"),  # Maximum file/text ingests per month
        # Query limits
        "hourly_query_limit": float("inf"),  # Maximum queries per hour
        "monthly_query_limit": float("inf"),  # Maximum queries per month
        # Graph limits
        "graph_creation_limit": float("inf"),  # Maximum number of graphs
        "hourly_graph_query_limit": float("inf"),  # Maximum graph queries per hour
        "monthly_graph_query_limit": float("inf"),  # Maximum graph queries per month
        # Cache limits
        "cache_creation_limit": float("inf"),  # Maximum number of caches
        "hourly_cache_query_limit": float("inf"),  # Maximum cache queries per hour
        "monthly_cache_query_limit": float("inf"),  # Maximum cache queries per month
    },
}


def get_tier_limits(tier: AccountTier, custom_limits: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Get limits for a specific account tier.

    Args:
        tier: The account tier
        custom_limits: Optional custom limits for CUSTOM tier

    Returns:
        Dict of limits for the specified tier
    """
    if tier == AccountTier.TEAMS and custom_limits:
        # Merge default custom limits with the provided custom limits
        return {**TIER_LIMITS[tier], **custom_limits}

    return TIER_LIMITS[tier]
