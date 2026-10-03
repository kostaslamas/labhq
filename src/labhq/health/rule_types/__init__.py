"""The rule types beyond `threshold`, each registered in `labhq.health.rules.registry` on import.

Importing this package is what makes them available; `labhq.health.incidents` and
`labhq.health.manage` do so. Metric names are the strings the collectors write (#76), agreed
by name rather than through a shared module.
"""

from labhq.health.rule_types import cert, http_probe, log_pattern, service, trend

__all__ = ["cert", "http_probe", "log_pattern", "service", "trend"]
