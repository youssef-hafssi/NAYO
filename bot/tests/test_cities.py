"""City detection from a free-text address (fills the city column; the client is never asked for it)."""

from app.cities import city_in_address, detect_city
from app.flow import place


def test_detect_city_spellings_and_scripts():
    assert detect_city("Hay Salam, rue 12, Agadir") == "Agadir"
    assert detect_city("Bd Zerktouni n°5, CASA") == "Casablanca"
    assert detect_city("حي السلام، الدار البيضاء") == "Casablanca"
    assert detect_city("lotissement Al Amal, fes") == "Fès"
    assert detect_city("Hay Riad, Ksar El Kebir") == "Ksar El Kébir"  # the longest name wins
    assert detect_city("Rue de Fès, Casablanca") == "Casablanca"  # a street named after a city loses to the city
    assert detect_city("Aït-Melloul, quartier industriel") == "Aït Melloul"
    assert detect_city("Douar Ait Ali, près de la mosquée") == ""
    assert detect_city("Casablancaise résidence") == ""  # whole words only
    assert detect_city("") == "" and detect_city(None) == ""


def test_place_in_the_recap():
    assert place("Agadir", "Hay Salam, rue 12") == "Agadir, Hay Salam, rue 12"
    assert place("Agadir", "Hay Salam, rue 12, Agadir") == "Hay Salam, rue 12, Agadir"
    assert place("Casablanca", "Bd Zerktouni, casa") == "Bd Zerktouni, casa"
    assert place("", "Douar Ait Ali") == "Douar Ait Ali"
    assert city_in_address("Fès", "rue 3, Fes") and not city_in_address("Rabat", "rue 3, Salé")
