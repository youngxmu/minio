from dataclasses import dataclass
from typing import Optional


DEFAULT_CAPACITY_FRACTION = 0.5


@dataclass(frozen=True)
class ColdTargetConfig:
    target_id: str
    endpoint: str
    cold_bucket: str
    cold_prefix: str
    tier_name: str
    minio_version: str
    usable_free_bytes: int


def default_max_migratable_bytes(
    usable_free_bytes: int,
    requested_max_bytes: Optional[int] = None,
    capacity_fraction: float = DEFAULT_CAPACITY_FRACTION,
) -> int:
    if usable_free_bytes < 0:
        raise ValueError("usable_free_bytes must be non-negative")
    if not 0 < capacity_fraction <= 1:
        raise ValueError("capacity_fraction must be in (0, 1]")

    calculated = int(usable_free_bytes * capacity_fraction)
    if requested_max_bytes is None:
        return calculated
    if requested_max_bytes < 0:
        raise ValueError("requested_max_bytes must be non-negative")
    return min(requested_max_bytes, calculated)


def validate_cold_target_config(config: ColdTargetConfig) -> None:
    required = {
        "target_id": config.target_id,
        "endpoint": config.endpoint,
        "cold_bucket": config.cold_bucket,
        "cold_prefix": config.cold_prefix,
        "tier_name": config.tier_name,
        "minio_version": config.minio_version,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError("missing required cold target fields: " + ", ".join(missing))
    if config.usable_free_bytes < 0:
        raise ValueError("usable_free_bytes must be non-negative")
