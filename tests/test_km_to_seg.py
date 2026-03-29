"""Tests unitaires pour Constraints.km_to_seg().

km_to_seg(km) = floor(km * nb_segments / total_km)
"""
import pytest
from relay.constraints import Constraints


def make_constraints(total_km: float, nb_segments: int) -> Constraints:
    return Constraints(
        total_km=total_km,
        nb_segments=nb_segments,
        speed_kmh=9.0,
        start_hour=15.0,
        compat_matrix={},
        solo_max_km=10.0,
        solo_max_default=3,
        nuit_max_default=2,
        repos_jour_heures=1.0,
        repos_nuit_heures=2.0,
    )


class TestKmToSeg:
    """Cas essentiels sur 440 km / 440 segments (1 km/seg) et 440/135."""

    def test_zero(self):
        c = make_constraints(440, 440)
        assert c.km_to_seg(0) == 0

    def test_exact_segment_boundary(self):
        # 10 km exact → segment 10
        c = make_constraints(440, 440)
        assert c.km_to_seg(10) == 10

    def test_within_segment(self):
        # 10.5 km → floor(10.5) = 10, encore dans le segment 10
        c = make_constraints(440, 440)
        assert c.km_to_seg(10.5) == 10

    def test_total_km(self):
        # 440 km → segment 440
        c = make_constraints(440, 440)
        assert c.km_to_seg(440) == 440

    def test_coherence_segment_km(self):
        # km_to_seg(seg_km) == 1 pour tout nb_segments
        for nb in (440, 135, 82):
            c = make_constraints(440, nb)
            seg_km = c.total_km / c.nb_segments
            assert c.km_to_seg(seg_km) == 1

    def test_135_segments(self):
        # 440 km / 135 segs → seg_km ≈ 3.259
        c = make_constraints(440, 135)
        assert c.km_to_seg(0) == 0
        assert c.km_to_seg(440) == 135
        # 220 km → floor(220 * 135 / 440) = floor(67.5) = 67
        assert c.km_to_seg(220) == 67
