"""Fixtures partagées pour les tests RelayConstraints."""

import pytest
from constraints import RelayConstraints


@pytest.fixture
def c():
    """RelayConstraints minimal synthétique : 100 km, 10 segments, départ à 15h."""
    return RelayConstraints(
        total_km=100.0,
        nb_segments=10,
        speed_kmh=10.0,
        start_hour=15.0,
        compat_matrix={
            ("Alice", "Bob"): 2,
            ("Bob", "Alice"): 2,
            ("Alice", "Carol"): 1,
            ("Carol", "Alice"): 1,
        },
        solo_max_km=15.0,
        solo_max_default=2,
        nuit_max_default=1,
        repos_jour_heures=7.0,
        repos_nuit_heures=9.0,
        nuit_debut=0.0,
        nuit_fin=6.0,
    )
