# app/routers/pointage.py
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import Carterfid, Candidat, Employe, Presence, PresenceEntree, Sortie
from app.schemas.schemas import BadgeScan

router = APIRouter(prefix="/api", tags=["pointage"])


@router.post("/scan-simulation", status_code=201, dependencies=[Depends(require_admin)])
async def scan_and_assign(
    payload: BadgeScan,
    db: AsyncSession = Depends(get_db),
):
    """
    Associe une carte RFID physique au candidat actuellement "actif",
    à condition que son employé ait déjà un poste (choisi par le candidat) et un
    visage enregistré. Aucune entrée n'est créée ici : l'employé devra
    présenter carte + visage à /api/biometrie/verify pour entrer.
    """
    if not payload.uidcarte:
        raise HTTPException(400, "uidcarte manquant")

    # 1. Trouver la carte
    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == payload.uidcarte))
    ).scalar_one_or_none()
    if not carte:
        raise HTTPException(404, "Carte RFID non trouvée")

    # 2. Vérifier qu'elle n'est pas déjà assignée
    deja_assignee = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if deja_assignee:
        raise HTTPException(409, "Cette carte est déjà assignée à un employé")

    # 3. Récupérer le candidat actuellement actif et son employé
    candidat = (
        await db.execute(select(Candidat).where(Candidat.statut == "actif"))
    ).scalar_one_or_none()
    if not candidat or not candidat.employe_id:
        raise HTTPException(
            404,
            "Aucun candidat actif avec un employé créé. Accepte d'abord via /candidats/{id}/accepter",
        )

    employe = await db.get(Employe, candidat.employe_id)
    if not employe:
        raise HTTPException(404, "Employé introuvable pour ce candidat")
    if employe.id_poste is None:
        raise HTTPException(
            409,
            "Cet employé n'a pas encore de poste : termine d'abord l'enrôlement du visage, "
            "puis le choix du poste depuis le téléphone du candidat "
            "(/candidats/{candidat_id}/choisir-poste).",
        )

    # 4. Assignation de la carte
    employe.carterfid_id = carte.id
    await db.commit()
    await db.refresh(employe)

    await manager.broadcast({
        "event": "carte_assignee",
        "employe_id": employe.id,
        "carte_uid": carte.uidcarte,
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "message": f"Carte remise à {candidat.nom}. Passage devant la caméra pour entrer.",
    })

    return {
        "success": True,
        "message": "Carte assignée à l'employé",
        "employe_id": employe.id,
        "carte_uid": carte.uidcarte,
    }


# ---------------------------------------------------------------------------
# Override manuel admin (carte seule, SANS visage) — n'est plus utilisé par
# la porte physique. La porte réelle doit toujours passer par
# /api/biometrie/verify (carte + visage) ; cet endpoint reste seulement
# comme dépannage admin (carte oubliée par le dispositif visage, test...).
# ---------------------------------------------------------------------------
@router.post("/entree", status_code=201, dependencies=[Depends(require_admin)])
async def gestion_presence(payload: BadgeScan, db: AsyncSession = Depends(get_db)):
    """
    Pointage manuel, carte seule, réservé à l'admin. Ne pas brancher sur
    le lecteur de la porte physique : il n'y a aucune vérification de
    visage ici, contrairement à /api/biometrie/verify.
    """
    if not payload.uidcarte:
        raise HTTPException(400, "uidcarte manquant")

    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == payload.uidcarte))
    ).scalar_one_or_none()
    if not carte:
        raise HTTPException(404, "Carte RFID non trouvée")

    employe = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if not employe:
        raise HTTPException(404, "Aucun employé lié à cette carte")

    if employe.status != "Actif":
        raise HTTPException(403, "Cet employé n'est plus actif")

    aujourdhui = date.today()
    heure_actuelle = datetime.now().time()

    if not carte.isentree:
        # Entrée
        entree = PresenceEntree(
            id_employe=employe.id,
            date=aujourdhui,
            heure_entree=heure_actuelle,
            ack=True,
        )
        carte.isentree = True

        presence = (
            await db.execute(
                select(Presence).where(
                    Presence.id_employe == employe.id,
                    Presence.datedujour == aujourdhui,
                )
            )
        ).scalar_one_or_none()

        if not presence:
            presence = Presence(
                id_employe=employe.id,
                datedujour=aujourdhui,
                statut="present",
                dureetravail=None,
            )
            db.add(presence)

        db.add(entree)
        await db.commit()

        await manager.broadcast({
            "event": "entree_entreprise",
            "message": f"{employe.nom} est entré dans l'entreprise.",
            "employe_id": employe.id,
            "nom": employe.nom,
        })

        return {
            "success": True,
            "type": "entree",
            "message": "Entrée enregistrée",
            "employe": {
                "id": employe.id,
                "nom": employe.nom,
                "matricule": employe.matricule,
            },
            "heure": heure_actuelle.strftime("%H:%M:%S"),
        }

    else:
        # Sortie
        sortie = Sortie(
            id_employe=employe.id,
            date=aujourdhui,
            heure_sortie=heure_actuelle,
        )
        carte.isentree = False

        db.add(sortie)
        await db.commit()

        await manager.broadcast({
            "event": "sortie_entreprise",
            "message": f"{employe.nom} est sorti de l'entreprise.",
            "employe_id": employe.id,
            "nom": employe.nom,
        })

        return {
            "success": True,
            "type": "sortie",
            "message": "Sortie enregistrée",
            "employe": {
                "id": employe.id,
                "nom": employe.nom,
                "matricule": employe.matricule,
            },
            "heure": heure_actuelle.strftime("%H:%M:%S"),
        }
