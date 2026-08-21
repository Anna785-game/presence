# app/routers/porte.py
"""
Endpoint dédié aux boîtiers physiques ESP32 (2 lecteurs RFID + servos +
LCD + LEDs), PAS au kiosque sys_ecran.

Rôle : vérifier UNIQUEMENT que la carte scannée est connue et assignée
à un employé actif, pour piloter le servo/LED du boîtier (ouverture de
porte). Ne vérifie AUCUN visage et ne touche PAS à carte.isentree, ni
aux tables Presence / PresenceEntree / Sortie : c'est sys_ecran (avec
sa propre caméra) qui reste seul responsable d'enregistrer l'entrée ou
la sortie réelle, via /api/biometrie/verify-entree ou /verify-sortie.

Flux voulu :
  1. Badge sur le boîtier ESP32 -> ce endpoint -> porte s'ouvre si la
     carte est valide.
  2. La personne se présente ensuite devant sys_ecran, qui scanne à
     nouveau la carte (lecteur USB) + prend une photo, et c'est LUI qui
     enregistre réellement l'entrée/la sortie dans la base.

Authentifié par un secret statique dans le header X-Porte-Secret (même
principe que X-Ecran-Secret pour le kiosque) : un ESP32 ne peut pas
gérer un JWT qui expire.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.db.models import Carterfid, Employe

router = APIRouter(prefix="/api/porte", tags=["porte"])


def _verifier_secret_porte(x_porte_secret: str | None):
    if x_porte_secret != settings.PORTE_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Secret porte invalide")


class VerifCarteRequest(BaseModel):
    uidcarte: str
    # "entree" ou "sortie" : uniquement informatif (logs), la logique ne
    # dépend pas du sens ici, contrairement à /api/biometrie/verify-entree.
    sens: str | None = None


@router.post("/verifier-carte")
async def verifier_carte(
    payload: VerifCarteRequest,
    db: AsyncSession = Depends(get_db),
    x_porte_secret: str | None = Header(default=None),
):
    _verifier_secret_porte(x_porte_secret)

    if not payload.uidcarte:
        raise HTTPException(400, "uidcarte manquant")

    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == payload.uidcarte))
    ).scalar_one_or_none()
    if not carte:
        return {"autorise": False, "raison": "carte_inconnue"}

    employe = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if not employe:
        return {"autorise": False, "raison": "carte_non_assignee"}

    if employe.status != "Actif":
        return {
            "autorise": False,
            "raison": "employe_inactif",
            "employe_id": employe.id,
        }

    return {
        "autorise": True,
        "employe_id": employe.id,
        "nom": employe.nom,
        "message": "Carte valide. Rendez-vous devant l'écran pour la vérification faciale.",
    }
