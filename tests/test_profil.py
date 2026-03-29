"""
Tests unitaires — relay/profil.py

Couvre :
1. Profile._altitude_at : interpolation linéaire, bornes, point exact
2. Profile.denivele : profil plat, montée pure, descente pure, mixte
3. Profile.denivele : inversion km_deb/km_fin → même résultat
4. Profile.denivele : intervalle d'un seul segment (< 100 m)
5. load_profile : chargement du CSV réel, valeurs de référence connues
"""

import math
import os
import pytest

from relay.profil import Profile, load_profile


# ---------------------------------------------------------------------------
# Helpers pour construire des profils synthétiques
# ---------------------------------------------------------------------------

def flat_profile(n=10, step=100.0, altitude=200.0) -> Profile:
    """Profil plat : n points espacés de `step` mètres à altitude constante."""
    distances = [i * step for i in range(n)]
    altitudes = [altitude] * n
    return Profile(distances, altitudes)


def ramp_profile() -> Profile:
    """
    Montée puis descente :
    0 m → 0 m alt
    100 m → 10 m alt
    200 m → 20 m alt
    300 m → 10 m alt
    400 m → 0 m alt
    """
    distances = [0, 100, 200, 300, 400]
    altitudes = [0, 10, 20, 10, 0]
    return Profile(distances, altitudes)


# ---------------------------------------------------------------------------
# Tests _altitude_at
# ---------------------------------------------------------------------------

class TestAltitudeAt:

    def test_point_exact(self):
        p = ramp_profile()
        assert p._altitude_at(0.1) == pytest.approx(10.0)   # 100 m = 0,1 km

    def test_interpolation_milieu(self):
        p = ramp_profile()
        # entre 0 m (0 m alt) et 100 m (10 m alt) → à 50 m = 5 m alt
        assert p._altitude_at(0.05) == pytest.approx(5.0)

    def test_borne_inferieure(self):
        p = ramp_profile()
        assert p._altitude_at(-1.0) == pytest.approx(0.0)

    def test_borne_superieure(self):
        p = ramp_profile()
        assert p._altitude_at(10.0) == pytest.approx(0.0)   # dernier point = 400 m, 0 m alt

    def test_profil_plat(self):
        p = flat_profile(altitude=350.0)
        assert p._altitude_at(0.5) == pytest.approx(350.0)


# ---------------------------------------------------------------------------
# Tests denivele
# ---------------------------------------------------------------------------

class TestDenivele:

    def test_plat(self):
        p = flat_profile()
        d_plus, d_moins = p.denivele(0.0, 0.5)
        assert d_plus == pytest.approx(0.0)
        assert d_moins == pytest.approx(0.0)

    def test_montee_pure(self):
        """0 → 0,2 km sur le profil rampe : montée de 0 à 20 m (d+ = 20, d- = 0)."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(0.0, 0.2)
        assert d_plus == pytest.approx(20.0)
        assert d_moins == pytest.approx(0.0)

    def test_descente_pure(self):
        """0,2 → 0,4 km sur le profil rampe : descente de 20 à 0 m (d+ = 0, d- = 20)."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(0.2, 0.4)
        assert d_plus == pytest.approx(0.0)
        assert d_moins == pytest.approx(20.0)

    def test_mixte(self):
        """Tout le profil rampe : d+ = 20, d- = 20."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(0.0, 0.4)
        assert d_plus == pytest.approx(20.0)
        assert d_moins == pytest.approx(20.0)

    def test_inversion_km_deb_km_fin(self):
        """L'ordre des bornes ne doit pas changer le résultat."""
        p = ramp_profile()
        fwd = p.denivele(0.0, 0.4)
        bwd = p.denivele(0.4, 0.0)
        assert fwd == bwd

    def test_intervalle_inferieur_pas(self):
        """Intervalle < 100 m (résolution du CSV) : uniquement les deux points interpolés."""
        p = ramp_profile()
        # entre 0,05 km (5 m alt) et 0,08 km (8 m alt) : montée pure de 3 m
        d_plus, d_moins = p.denivele(0.05, 0.08)
        assert d_plus == pytest.approx(3.0)
        assert d_moins == pytest.approx(0.0)

    def test_intervalle_nul(self):
        """km_deb == km_fin → d+ = d- = 0."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(0.1, 0.1)
        assert d_plus == pytest.approx(0.0)
        assert d_moins == pytest.approx(0.0)

    def test_d_plus_d_moins_positifs(self):
        """d_moins doit toujours être >= 0."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(0.2, 0.4)
        assert d_moins >= 0.0

    def test_km_deb_negatif(self):
        """km_deb < 0 : la partie hors profil est plate → même résultat que depuis 0."""
        p = ramp_profile()
        ref = p.denivele(0.0, 0.2)
        oob = p.denivele(-1.0, 0.2)
        assert oob == pytest.approx(ref)

    def test_km_fin_depasse_profil(self):
        """km_fin > longueur du profil : la partie hors profil est plate → même résultat qu'à la fin."""
        p = ramp_profile()
        ref = p.denivele(0.2, 0.4)
        oob = p.denivele(0.2, 10.0)
        assert oob == pytest.approx(ref)

    def test_les_deux_bornes_hors_profil_meme_cote(self):
        """km_deb et km_fin tous les deux au-delà de la fin : altitude constante → d+ = d- = 0."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(5.0, 10.0)
        assert d_plus == pytest.approx(0.0)
        assert d_moins == pytest.approx(0.0)

    def test_les_deux_bornes_avant_debut(self):
        """km_deb et km_fin tous les deux avant le début du profil : d+ = d- = 0."""
        p = ramp_profile()
        d_plus, d_moins = p.denivele(-2.0, -0.5)
        assert d_plus == pytest.approx(0.0)
        assert d_moins == pytest.approx(0.0)

    def test_profil_encadre_par_hors_bornes(self):
        """km_deb très négatif et km_fin très grand : les parties hors profil sont plates,
        le dénivelé doit être identique à celui du profil entier."""
        p = ramp_profile()
        ref = p.denivele(0.0, 0.4)
        oob = p.denivele(-5.0, 5.0)
        assert oob == pytest.approx(ref)


# ---------------------------------------------------------------------------
# Tests load_profile (intégration avec le vrai CSV)
# ---------------------------------------------------------------------------

class TestLoadProfile:

    @pytest.fixture(scope="class")
    def profile(self):
        csv_path = os.path.join(
            os.path.dirname(__file__), "..", "gpx", "altitude.csv"
        )
        return load_profile(csv_path)

    def test_charge_sans_erreur(self, profile):
        assert profile is not None

    def test_nombre_points(self, profile):
        # Le CSV couvre 0 à 439 300 m par pas de 100 m → 4394 points
        assert len(profile._distances) == 4394

    def test_premiere_distance(self, profile):
        assert profile._distances[0] == pytest.approx(0.0)

    def test_derniere_distance(self, profile):
        assert profile._distances[-1] == pytest.approx(439300.0)

    def test_altitude_depart(self, profile):
        # Le CSV indique 173 m à 0 m
        assert profile._altitude_at(0.0) == pytest.approx(173.0)

    def test_denivele_total_coherent(self, profile):
        """D+ et D- sur le trajet complet doivent être dans l'ordre de grandeur
        des 5591 m / 5560 m annoncés dans l'en-tête du CSV."""
        d_plus, d_moins = profile.denivele(0.0, 439.3)
        assert 4000 < d_plus < 7000
        assert 4000 < d_moins < 7000

    def test_denivele_segment_court(self, profile):
        """Un segment de 2,5 km ne doit pas dépasser ~500 m de dénivelé."""
        d_plus, d_moins = profile.denivele(0.0, 2.5)
        assert d_plus < 500
        assert d_moins < 500
