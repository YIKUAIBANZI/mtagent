"""Dianping API request signing.

Per the official docs:
1. Lowercase all parameter names.
2. Sort by ASCII order on the lowercased name.
3. Exclude `appsecrect` itself, empty/None values, and the `content` field
   (UGC content is too big to participate in signing efficiently).
4. Concatenate as key1value1key2value2...
5. Wrap with the secret on both sides.
6. UTF-8 encode → MD5 → hex lowercase.

Example: a=1, b=2, ab=3, secret=xyz
  → sorted lowercased: ab=3, a=1, b=2
  → concat: ab3a1b2
  → wrapped: xyzab3a1b2xyz
  → md5(utf8) hex lowercase
"""

import hashlib

EXCLUDED_KEYS = {"appsecrect", "content", "sign"}


def sign(params: dict, appsecrect: str) -> str:
    """Compute Dianping signature for a request parameter dict."""
    items = []
    for k, v in params.items():
        if v is None or v == "":
            continue
        k_lower = k.lower()
        if k_lower in EXCLUDED_KEYS:
            continue
        items.append((k_lower, str(v)))
    items.sort(key=lambda x: x[0])
    concat = "".join(f"{k}{v}" for k, v in items)
    raw = f"{appsecrect}{concat}{appsecrect}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()
