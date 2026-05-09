"""Test signature algorithm against the official documentation example."""

import hashlib


def test_signature_doc_example():
    """Per docs: a=1, b=2, ab=3, secret=xyz → concat 'xyza1ab3b2xyz' → MD5."""
    from dianping.auth import sign

    params = {"a": 1, "b": 2, "ab": 3}
    secret = "xyz"

    expected_concat = "xyza1ab3b2xyz"
    expected = hashlib.md5(expected_concat.encode("utf-8")).hexdigest().lower()

    assert sign(params, secret) == expected


def test_signature_excludes_empty_values():
    """Empty-string and None param values must be excluded from signing."""
    from dianping.auth import sign

    params_with_empty = {"a": 1, "b": "", "c": None, "ab": 3}
    params_clean = {"a": 1, "ab": 3}

    assert sign(params_with_empty, "secret") == sign(params_clean, "secret")


def test_signature_lowercases_keys():
    """Per docs: parameter names must be lowercased before sorting."""
    from dianping.auth import sign

    params_upper = {"A": 1, "B": 2, "AB": 3}
    params_lower = {"a": 1, "b": 2, "ab": 3}

    assert sign(params_upper, "xyz") == sign(params_lower, "xyz")


def test_signature_excludes_appsecrect_param():
    """appsecrect param itself (if present in dict) must not participate in signing."""
    from dianping.auth import sign

    params_with_secret = {"a": 1, "appsecrect": "xyz", "b": 2, "ab": 3}
    params_without = {"a": 1, "b": 2, "ab": 3}

    assert sign(params_with_secret, "xyz") == sign(params_without, "xyz")


def test_signature_excludes_content_field():
    """Per UGC docs: 'content' field is excluded for signing efficiency."""
    from dianping.auth import sign

    huge_content = "X" * 10000
    params_with = {"a": 1, "b": 2, "content": huge_content}
    params_without = {"a": 1, "b": 2}

    assert sign(params_with, "xyz") == sign(params_without, "xyz")


def test_signature_returns_lowercase_hex():
    """Per docs: result is hex lowercase."""
    from dianping.auth import sign

    result = sign({"a": 1}, "xyz")
    assert result == result.lower()
    assert len(result) == 32  # MD5 hex is 32 chars
