# app/core/time_utils.py
"""
Le serveur (Render ou autre) tourne en UTC. Ton fuseau (Madagascar,
Indian/Antananarivo) est UTC+3. Sans conversion explicite, datetime.now()
et date.today() renvoient l'heure DU SERVEUR, pas la tienne : entre 21h00
et minuit chez toi, le serveur est encore "le jour d'avant", ce qui fausse
la date/l'heure enregistrées sur chaque entrée/sortie et le filtre
/historique/jour?date=....

Remplace TOUS les `datetime.now()` par `maintenant()`, et tous les
`date.today()` par `aujourdhui()`, dans pointage.py, biometrie.py,
simulation_events.py, historique_jour.py, etc.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSEAU_LOCAL = ZoneInfo("Indian/Antananarivo")  # UTC+3, pas de changement d'heure d'été


def maintenant() -> datetime:
    """Équivalent de datetime.now(), mais dans le fuseau local au lieu de celui du serveur."""
    return datetime.now(FUSEAU_LOCAL)


def aujourdhui() -> date:
    """Équivalent de date.today(), mais dans le fuseau local au lieu de celui du serveur."""
    return maintenant().date()