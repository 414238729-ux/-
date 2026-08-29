# -*- coding: utf-8 -*-
"""Shared current-development implementation identity pin.

This mutable development pin is intentionally outside the frozen historical
R8 evidence and outside the implementation-identity input inventory, avoiding
a self-referential hash.  Tests import it through the normal repository Python
path, so the comparison executes under an ordinary ``pytest`` collection.
"""

POST_B_CURRENT_IMPLEMENTATION_IDENTITY = (
    "af66c568eb0c4b166139e24349f6e46e2a4735949125a326dde0490b8ade434e"
)
