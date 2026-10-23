"""The vocabulary of docs/format-spec.md: the values each field may take."""
from __future__ import annotations

import re

KINDS = {"standing", "territory"}
VOLATILITIES = {"stable", "slow", "live"}
STATUSES = {"SHIPPED", "PARKED", "STILL LIVE", "BLOCKED", "IN FLIGHT", "RESOLVED", "HISTORICAL"}
ROLES = {"gate", "reference"}
CONFIDENCES = {"asserted", "inferred"}
OWNERS = {"self", "colleague", "employer", "third-party"}
MODES = {"active", "occasional-pr", "reference", "dead-upstream", "scratch", "parked"}
TIERS = {"state", "record"}

STATUS_VOLATILITY = {
    "SHIPPED": "stable", "RESOLVED": "stable", "HISTORICAL": "stable",
    "PARKED": "slow",
    "STILL LIVE": "live", "BLOCKED": "live", "IN FLIGHT": "live",
}
STALE_AFTER = {"stable": 365, "slow": 90, "live": 14}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
INDEX_LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")

# The accretion markers direction §2 counted (24 files of 296): a mutable file acting as a log.
# The phrases match in any case ("History below"); CORRECTION and SUPERSEDED only shouted, since
# in lower case they are ordinary prose.
ACCRETION_RE = re.compile(r"(?i:read bottom-up|history below)|CORRECTION|SUPERSEDED")
