"""Tests unitaires de Solution : sérialisation/désérialisation JSON."""

import json
import pytest

from relay.constraints import Constraints
from relay.solution import Solution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def constraints():
    c = Constraints(
        total_km=100.0,
        nb_segments=10,
        speed_kmh=10.0,
        start_hour=15.0,
        compat_matrix={("Alice", "Bob"): 2, ("Bob", "Alice"): 2},
        solo_max_km=15.0,
        solo_max_default=2,
        nuit_max_default=1,
        repos_jour_heures=7.0,
        repos_nuit_heures=9.0,
        nuit_debut=0.0,
        nuit_fin=6.0,
    )
    return c


def _minimal_relay(**overrides):
    base = {
        "runner": "Alice",
        "k": 0,
        "start": 0,
        "end": 10,
        "size": 10,
        "size_decl": 10,
        "km": 10.0,
        "flex": False,
        "solo": True,
        "night": False,
        "partner": None,
        "pinned": None,
        "rest_h": None,
        "rest_min_segs": 7,
        "d_plus": None,
        "d_moins": None,
    }
    base.update(overrides)
    return base


def _make_solution(constraints, *relays):
    return Solution(list(relays), constraints, skip_validation=True)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    def test_returns_dict_with_relays_and_constraints(self, constraints):
        s = _make_solution(constraints, _minimal_relay())
        d = s.to_dict()
        assert isinstance(d, dict)
        assert "relays" in d
        assert "constraints" in d

    def test_relays_list(self, constraints):
        relay = _minimal_relay()
        s = _make_solution(constraints, relay)
        assert s.to_dict()["relays"] == [relay]

    def test_multiple_relays_order_preserved(self, constraints):
        r1 = _minimal_relay(runner="Alice", k=0, start=0)
        r2 = _minimal_relay(runner="Bob", k=0, start=5)
        s = _make_solution(constraints, r1, r2)
        assert s.to_dict()["relays"] == [r1, r2]

    def test_relays_is_same_object(self, constraints):
        """to_dict()['relays'] gives direct access to the internal list — no copy."""
        relay = _minimal_relay()
        s = _make_solution(constraints, relay)
        assert s.to_dict()["relays"] is s.relays


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------

class TestFromDict:
    def test_roundtrip(self, constraints):
        relay = _minimal_relay()
        s = Solution([relay], constraints, skip_validation=True)
        s2 = Solution.from_dict(s.to_dict(), skip_validation=True)
        assert s2.relays == [relay]

    def test_valid_is_none_with_skip_validation(self, constraints):
        s = Solution([_minimal_relay()], constraints, skip_validation=True)
        s2 = Solution.from_dict(s.to_dict(), skip_validation=True)
        assert s2.valid is None

    def test_empty_relays(self, constraints):
        s = Solution([], constraints, skip_validation=True)
        s2 = Solution.from_dict(s.to_dict(), skip_validation=True)
        assert s2.relays == []

    def test_preserves_all_fields(self, constraints):
        relay = _minimal_relay(partner="Bob", flex=True, night=True, d_plus=42.5, d_moins=30.0)
        s = Solution([relay], constraints, skip_validation=True)
        s2 = Solution.from_dict(s.to_dict(), skip_validation=True)
        assert s2.relays[0]["partner"] == "Bob"
        assert s2.relays[0]["d_plus"] == 42.5

    def test_constraints_reconstructed(self, constraints):
        s = Solution([_minimal_relay()], constraints, skip_validation=True)
        s2 = Solution.from_dict(s.to_dict(), skip_validation=True)
        assert s2.constraints is not None
        assert s2.constraints.total_km == constraints.total_km
        assert s2.constraints.nb_active_segments == constraints.nb_active_segments


# ---------------------------------------------------------------------------
# to_json / from_json round-trip
# ---------------------------------------------------------------------------

class TestJsonFileRoundtrip:
    def test_roundtrip_via_file(self, constraints, tmp_path):
        relay = _minimal_relay()
        s = _make_solution(constraints, relay)
        path = str(tmp_path / "sol.json")
        s.to_json(path)
        s2 = Solution.from_json(path, skip_validation=True)
        assert s2.relays == s.relays

    def test_file_is_valid_json(self, constraints, tmp_path):
        s = _make_solution(constraints, _minimal_relay())
        path = tmp_path / "sol.json"
        s.to_json(str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "relays" in data
        assert "constraints" in data

    def test_unicode_runner_name(self, constraints, tmp_path):
        relay = _minimal_relay(runner="Élodie")
        s = _make_solution(constraints, relay)
        path = str(tmp_path / "sol.json")
        s.to_json(path)
        s2 = Solution.from_json(path, skip_validation=True)
        assert s2.relays[0]["runner"] == "Élodie"

    def test_none_values_preserved(self, constraints, tmp_path):
        relay = _minimal_relay(partner=None, rest_h=None, d_plus=None)
        s = _make_solution(constraints, relay)
        path = str(tmp_path / "sol.json")
        s.to_json(path)
        s2 = Solution.from_json(path, skip_validation=True)
        assert s2.relays[0]["partner"] is None
        assert s2.relays[0]["rest_h"] is None
        assert s2.relays[0]["d_plus"] is None

    def test_multiple_relays(self, constraints, tmp_path):
        relays = [_minimal_relay(runner="Alice", k=i, start=i * 10) for i in range(5)]
        s = Solution(relays, constraints, skip_validation=True)
        path = str(tmp_path / "sol.json")
        s.to_json(path)
        s2 = Solution.from_json(path, skip_validation=True)
        assert len(s2.relays) == 5
        assert [r["k"] for r in s2.relays] == [0, 1, 2, 3, 4]

    def test_constraints_survive_roundtrip(self, constraints, tmp_path):
        s = _make_solution(constraints, _minimal_relay())
        path = str(tmp_path / "sol.json")
        s.to_json(path)
        s2 = Solution.from_json(path, skip_validation=True)
        assert s2.constraints.speed_kmh == constraints.speed_kmh
        assert s2.constraints.start_hour == constraints.start_hour


# ---------------------------------------------------------------------------
# to_dict / from_dict in-memory round-trip (no I/O)
# ---------------------------------------------------------------------------

class TestInMemoryRoundtrip:
    def test_dict_roundtrip_no_file(self, constraints):
        relay = _minimal_relay(partner="Bob", flex=True, rest_h=8.5)
        s = _make_solution(constraints, relay)
        s2 = Solution.from_dict(s.to_dict(), skip_validation=True)
        assert s2.relays == s.relays

    def test_json_string_roundtrip(self, constraints):
        relay = _minimal_relay()
        s = _make_solution(constraints, relay)
        serialised = json.dumps(s.to_dict(), ensure_ascii=False)
        data = json.loads(serialised)
        s2 = Solution.from_dict(data, skip_validation=True)
        assert s2.relays == s.relays
