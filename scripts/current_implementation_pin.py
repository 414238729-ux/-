# -*- coding: utf-8 -*-
"""Shared current-development implementation identity pin.

This mutable development pin is intentionally outside the frozen historical
R8 evidence and outside the implementation-identity input inventory, avoiding
a self-referential hash.  Tests import it through the normal repository Python
path, so the comparison executes under an ordinary ``pytest`` collection.
"""

POST_B_CURRENT_IMPLEMENTATION_IDENTITY = (
    "da73a75e195153f61a89012adf9f84b309194e2a71889ef2059fb847dbfa22d1"
)
