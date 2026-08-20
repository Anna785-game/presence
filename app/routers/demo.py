# app/routers/demo.py
"""
Mode démo sans RFID physique.
Mot de passe fixe (expo) : azerty
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import Candidat, Employe, Carterfid

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_PASSWORD = "azerty"
FAKE_TTL = timedelta(hours=1)


class DemoAuth(BaseModel):
    candidat_id: int
    password: str


def _check_pwd(password: str):
    if password != DEMO_PASSWORD:
        raise HTTPException(403, "Mot de passe incorrect")


async def _get_candidat_employe(db: AsyncSession, candidat_id: int):
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat introuvable")
    if candidat.statut != "actif":
        raise HTTPException(409, "Le candidat doit être actif")
    if not candidat.employe_id:
        raise HTTPException(400, "Aucun employé lié")
    if not candidat.poste_attribue:
        raise HTTPException(409, "Poste non encore choisi")
    employe = await db.get(Employe, candidat.employe_id)
    if not employe or employe.status != "Actif":
        raise HTTPException(409, "Employé inactif ou manquant")
    return candidat, employe


async def _purge_expired_fakes(db: AsyncSession):
    """Supprime les cartes FAKE-* de plus d'1 h et détache les employés."""
    cutoff = datetime.now(timezone.utc) - FAKE_TTL
    # uid format: FAKE-{candidat_id}-{unix_ts}
    cartes = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte.startswith("FAKE-")))
    ).scalars().all()
    for c in cartes:
        try:
            ts = int(c.uidcarte.rsplit("-", 1)[-1])
            created = datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            continue
        if created < cutoff:
            emp = (
                await db.execute(select(Employe).where(Employe.carterfid_id == c.id))
            ).scalar_one_or_none()
            if emp:
                emp.carterfid_id = None
            await db.delete(c)
    await db.commit()


@router.post("/carte-factice")
async def activer_carte_factice(payload: DemoAuth, db: AsyncSession = Depends(get_db)):
    _check_pwd(payload.password)
    await _purge_expired_fakes(db)

    candidat, employe = await _get_candidat_employe(db, payload.candidat_id)

    # Déjà une FAKE récente ?
    if employe.carterfid_id:
        carte = await db.get(Carterfid, employe.carterfid_id)
        if carte and carte.uidcarte and carte.uidcarte.startswith("FAKE-"):
            return {
                "success": True,
                "uidcarte": carte.uidcarte,
                "message": "Carte factice déjà active.",
                "expires_in_minutes": 60,
            }

    ts = int(datetime.now(timezone.utc).timestamp())
    uid = f"FAKE-{candidat.id}-{ts}"
    carte = Carterfid(uidcarte=uid, couleur="or", isentree=False)
    db.add(carte)
    await db.flush()
    employe.carterfid_id = carte.id
    await db.commit()

    await manager.broadcast({
        "event": "carte_assignee",
        "employe_id": employe.id,
        "carte_uid": uid,
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "message": f"Carte factice remise à {candidat.nom} (expire dans 1 h).",
        "factice": True,
    })

    return {
        "success": True,
        "uidcarte": uid,
        "employe_id": employe.id,
        "nom": candidat.nom,
        "poste": candidat.poste_attribue,
        "message": "Vous avez utilisé la carte factice, monseigneur.",
        "expires_in_minutes": 60,
    }


@router.post("/simuler-scan")
async def simuler_scan(payload: DemoAuth, db: AsyncSession = Depends(get_db)):
    """
    Simule le lecteur RFID : broadcast vers /ws/ecran.
    Le kiosque démarre la phase caméra comme après un vrai badge.
    """
    _check_pwd(payload.password)
    await _purge_expired_fakes(db)

    candidat, employe = await _get_candidat_employe(db, payload.candidat_id)
    if not employe.carterfid_id:
        raise HTTPException(409, "Active d'abord la carte factice")

    carte = await db.get(Carterfid, employe.carterfid_id)
    if not carte or not carte.uidcarte:
        raise HTTPException(409, "Carte introuvable")
    if not carte.uidcarte.startswith("FAKE-"):
        raise HTTPException(409, "Ce n'est pas une carte factice")

    await manager.broadcast({
        "event": "scan_factice",
        "uidcarte": carte.uidcarte,
        "employe_id": employe.id,
        "nom": candidat.nom,
        "message": f"Scan factice : {candidat.nom} — placez-vous devant l'écran.",
    })

    return {
        "success": True,
        "uidcarte": carte.uidcarte,
        "message": "Vous avez utilisé la carte factice, monseigneur. Passez devant la caméra.",
    }