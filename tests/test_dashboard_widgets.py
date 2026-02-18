"""Tests for dashboard widget helpers (fg_color, indicator_color)."""

from __future__ import annotations

import pytest

from insider_scanner.gui.widgets import fg_color, indicator_color


# -------------------------------------------------------------------
# fg_color
# -------------------------------------------------------------------


class TestFgColor:
    def test_extreme_fear(self):
        r, g, b, a = fg_color(10)
        assert r > g  # Red-dominant

    def test_fear(self):
        r, g, b, a = fg_color(35)
        assert r > b  # Orange-ish

    def test_greed(self):
        r, g, b, a = fg_color(60)
        assert r > b  # Yellow-ish

    def test_extreme_greed(self):
        r, g, b, a = fg_color(80)
        assert g > r  # Green-dominant

    @pytest.mark.parametrize("v", [0, 24, 25, 49, 50, 74, 75, 100])
    def test_all_boundary_values_return_tuple(self, v):
        result = fg_color(v)
        assert isinstance(result, tuple)
        assert len(result) == 4


# -------------------------------------------------------------------
# indicator_color
# -------------------------------------------------------------------


class TestIndicatorColor:
    BANDS = (
        (0, 30, "green"),
        (30, 70, "yellow"),
        (70, 100, "red"),
    )

    def test_in_first_band(self):
        r, g, b, a = indicator_color(15, self.BANDS)
        assert g > r  # green

    def test_in_middle_band(self):
        r, g, b, a = indicator_color(50, self.BANDS)
        assert g > b  # yellow (high r and g)

    def test_in_last_band(self):
        r, g, b, a = indicator_color(85, self.BANDS)
        assert r > g  # red

    def test_outside_all_bands(self):
        """Value below/above all bands gets gray."""
        result = indicator_color(-5, self.BANDS)
        assert result == (80, 80, 80, 120)

    def test_exact_boundary(self):
        """lo <= value < hi: value=30 should be in the (30,70) band."""
        r, g, b, a = indicator_color(30, self.BANDS)
        assert g > b  # yellow

    def test_empty_bands(self):
        result = indicator_color(50, ())
        assert result == (80, 80, 80, 120)  # gray fallback

    def test_unknown_color_name(self):
        bands = ((0, 100, "magenta"),)  # not in palette
        result = indicator_color(50, bands)
        assert result == (80, 80, 80, 120)  # gray fallback
