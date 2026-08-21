# app/core/porte_pending.py
"""
État temporaire des ouvertures de porte en attente de validation faciale.
In-mémoire (suffisant pour une maquette / expo).
Clé = uidcarte normalisé.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

@dataclass
class PendingOpen:
    uidcarte: str
    sens: str                    # "entree" | "sortie"
    employe_id: int
    nom: str
    authorized: bool = False     # True quand le visage a été validé
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    authorized_at: Optional[datetime] = None


# uid → PendingOpen
_pending: dict[str, PendingOpen] = {}


def create_pending(uid: str, sens: str, employe_id: int, nom: str) -> PendingOpen:
    p = PendingOpen(uidcarte=uid, sens=sens or "entree", employe_id=employe_id, nom=nom or "")
    _pending[uid] = p
    return p


def mark_authorized(uid: str) -> bool:
    """Appelé quand /api/biometrie/verify renvoie AUTHORIZED."""
    p = _pending.get(uid)
    if not p:
        return False
    p.authorized = True
    p.authorized_at = datetime.now(timezone.utc)
    return True


def get_pending(uid: str) -> Optional[PendingOpen]:
    return _pending.get(uid)


def consume_if_authorized(uid: str) -> Optional[PendingOpen]:
    """Retourne le pending s'il est autorisé, et le supprime (one-shot)."""
    p = _pending.get(uid)
    if not p or not p.authorized:
        return None
    del _pending[uid]
    return p


def clear_old(max_age_seconds: int = 90):
    """Nettoyage simple des demandes trop vieilles."""
    now = datetime.now(timezone.utc)
    to_del = [
        uid for uid, p in _pending.items()
        if (now - p.created_at).total_seconds() > max_age_seconds
    ]
    for uid in to_del:
        _pending.pop(uid, None)


def clear_pending(uid: str) -> None:
    _pending.pop(uid, None)