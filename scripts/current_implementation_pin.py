# -*- coding: utf-8 -*-
"""Shared current-development implementation identity pin.

This mutable development pin is intentionally outside the frozen historical
R8 evidence and outside the implementation-identity input inventory, avoiding
a self-referential hash.  Tests import it through the normal repository Python
path, so the comparison executes under an ordinary ``pytest`` collection.
"""

POST_B_CURRENT_IMPLEMENTATION_IDENTITY = (
    "7394e4ca25c85f4e9454bad363c707c7a1487d0b027c014c4d8708c176359c66"
)
