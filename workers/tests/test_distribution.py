"""Tests for enrichment/distribution.py."""
from __future__ import annotations

from cp_workers.enrichment.distribution import distribution_breadth


def test_no_stockists_no_marketplace_is_zero():
    assert distribution_breadth([], None) == 0.0
    assert distribution_breadth(None, None) == 0.0


def test_many_stockists_and_marketplace_is_high():
    stockists = [f"Retailer {i}" for i in range(10)]
    value = distribution_breadth(stockists, {"present": True, "review_count": 500})
    assert value > 0.8


def test_few_stockists_scores_lower_than_many():
    few = distribution_breadth(["Retailer A"], None)
    many = distribution_breadth([f"Retailer {i}" for i in range(10)], None)
    assert few < many


def test_marketplace_bool_shorthand_supported():
    assert distribution_breadth([], True) > distribution_breadth([], False)


def test_thin_marketplace_listing_scores_less_than_established_one():
    thin = distribution_breadth([], {"present": True, "review_count": 2})
    established = distribution_breadth([], {"present": True, "review_count": 200})
    assert thin < established


def test_never_raises_on_malformed_stockist_entries():
    result = distribution_breadth(["", None, "Real Stockist"], {"present": False})  # type: ignore[list-item]
    assert 0.0 <= result <= 1.0


def test_bounded_between_0_and_1():
    stockists = [f"Retailer {i}" for i in range(50)]
    value = distribution_breadth(stockists, {"present": True, "review_count": 10000})
    assert value <= 1.0
