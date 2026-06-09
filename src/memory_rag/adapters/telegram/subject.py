"""Adapter-owned community→subject resolver (H-2; D-097).

The single site that assigns a core ``subject_id`` to an inbound note.
This is the D-026 axis-5 (tenant/auth mapping) function, parallel to the
chat→community resolver (``community.py`` / D-094): *the mapping function
is adapter; the scoped query is core*. The core receives the already-
resolved opaque ``subject_id`` (or ``None``) and never derives a subject
from a host identity field (I-1).

``subject_id`` is subordinate to ``community_id`` — it never widens or
crosses community scope (I-7 / R-3 / R-8 stay the outer boundary). The
default first-use-case mapping is **single-subject per community**: one
subject per community, which is community-wide, which is ``None`` (D-097
§3 "``null`` = community-wide"). Returning ``None`` keeps assignment
behavior- and data-preserving versus today; the seam exists so a future
host plugs a non-default mapping here (e.g. a per-sender subject lookup)
without touching any core call site.
"""

from __future__ import annotations


def resolve_subject_id(community_id: str) -> str | None:
    """Map a community scope to an opaque core ``subject_id``.

    Default mapping is single-subject per community → community-wide →
    ``None``. The return value is opaque past the adapter edge — the core
    treats it as a scope id, never decoding it.
    """
    return None
