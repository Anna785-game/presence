# app/routers/biometrie.py
"""
Identique à l'original, SAUF :
  - les imports de app.core.biometrie -> app.core.face_client (appel HTTP
    vers ton PC au lieu d'un calcul local)
  - ajout de la gestion de FaceServerIndisponible -> 503, pour ne pas
    planter bêtement si ton PC/tunnel est down pendant l'expo.
  - /enroll/{employe_id} n'utilise plus require_admin (JWT qui expire au
    bout d'1h) mais un secret statique X-Ecran-Secret, comme l'écran
    kiosque (voir app/routers/candidats.py::tache_active_ecran). Doit
    correspondre à settings.ECRAN_SHARED_SECRET.
Tout le reste (roulette, DB, websockets, logique carte+visage) est
inchangé.
"""
import random
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.face_client import (
    SEUIL_DEFAUT,
    AucunVisageDetecte,
    FaceServerIndisponible,
    PlusieursVisagesDetectes,
    image_bytes_vers_encoding,
    visage_correspond,
)
from app.core.biometrie_hooks import nettoyer_biometrie_employe
from app.core.security import require_admin
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import (
    Candidat,
    Carterfid,
    Employe,
    FaceEncoding,
    Poste,
    Presence,
    PresenceEntree,
    Sortie,
)

router = APIRouter(prefix="/api/biometrie", tags=["biometrie"])


def _verifier_secret_ecran(x_ecran_secret: str | None):
    if x_ecran_secret != settings.ECRAN_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Secret écran invalide")


@router.post("/enroll/{employe_id}")
async def enroll_visage(
    employe_id: int,
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    x_ecran_secret: str | None = Header(default=None),
):
    _verifier_secret_ecran(x_ecran_secret)

    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")
    if employe.status != "Actif":
        raise HTTPException(409, "Impossible d'enregistrer un visage pour un employé inactif")

    contenu = await photo.read()
    try:
        encoding = await image_bytes_vers_encoding(contenu)
    except AucunVisageDetecte:
        raise HTTPException(422, "Aucun visage détecté : replace-toi dans le cadre")
    except PlusieursVisagesDetectes:
        raise HTTPException(422, "Plusieurs visages détectés : une seule personne à la fois dans le cadre")
    except FaceServerIndisponible:
        raise HTTPException(503, "Service de reconnaissance faciale indisponible (PC hors ligne ?)")

    existant = (
        await db.execute(select(FaceEncoding).where(FaceEncoding.employe_id == employe_id))
    ).scalar_one_or_none()

    if existant:
        existant.encoding = encoding
    else:
        db.add(FaceEncoding(employe_id=employe_id, encoding=encoding))

    poste_gagnant = None
    candidat = None
    if employe.id_poste is None:
        postes = (await db.execute(select(Poste))).scalars().all()
        if not postes:
            raise HTTPException(400, "Aucun poste configuré (lance /postes/seed-demo)")

        poids = [p.poids or 1 for p in postes]
        total_poids = sum(poids)
        poste_gagnant = random.choices(postes, weights=poids, k=1)[0]
        employe.id_poste = poste_gagnant.id

        candidat = (
            await db.execute(select(Candidat).where(Candidat.employe_id == employe_id))
        ).scalar_one_or_none()
        if candidat:
            candidat.poste_attribue = poste_gagnant.type_poste

    await db.commit()
    await db.refresh(employe)

    if poste_gagnant:
        repartition = [
            {
                "poste": p.type_poste,
                "pourcentage": round((p.poids or 1) / total_poids * 100, 1),
            }
            for p in postes
        ]
        await manager.broadcast({
            "event": "roulette",
            "employe_id": employe.id,
            "poste_gagnant": poste_gagnant.type_poste,
            "repartition": repartition,
            "candidat": {"id": candidat.id, "nom": candidat.nom} if candidat else None,
        })
        await manager.broadcast({
            "event": "employe_actif",
            "employe_id": employe.id,
            "poste": poste_gagnant.type_poste,
            "message": f"Félicitations ! Vous êtes maintenant employé en tant que {poste_gagnant.type_poste}.",
        })

    return {
        "success": True,
        "message": "Visage enregistré avec succès",
        "employe_id": employe_id,
        "poste_attribue": poste_gagnant.type_poste if poste_gagnant else None,
    }


@router.post("/verify")
async def verifier_visage(
    uidcarte: str = Form(...),
    photo: UploadFile = File(...),
    seuil: float = Form(SEUIL_DEFAUT),
    db: AsyncSession = Depends(get_db),
):
    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == uidcarte))
    ).scalar_one_or_none()
    if not carte:
        return {"result": "DENIED", "reason": "carte_inconnue"}

    employe = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if not employe:
        return {"result": "DENIED", "reason": "carte_non_assignee"}

    if employe.status != "Actif":
        await manager.broadcast({
            "event": "acces_refuse",
            "reason": "employe_inactif",
            "employe_id": employe.id,
            "message": "Accès refusé : employé inactif.",
        })
        return {"result": "DENIED", "reason": "employe_inactif", "employe_id": employe.id}

    face_row = (
        await db.execute(select(FaceEncoding).where(FaceEncoding.employe_id == employe.id))
    ).scalar_one_or_none()
    if not face_row:
        return {"result": "DENIED", "reason": "aucun_visage_enregistre", "employe_id": employe.id}

    contenu = await photo.read()
    try:
        encoding_actuel = await image_bytes_vers_encoding(contenu)
    except AucunVisageDetecte:
        return {"result": "DENIED", "reason": "aucun_visage_detecte", "employe_id": employe.id}
    except PlusieursVisagesDetectes:
        return {"result": "DENIED", "reason": "plusieurs_visages_detectes", "employe_id": employe.id}
    except FaceServerIndisponible:
        raise HTTPException(503, "Service de reconnaissance faciale indisponible (PC hors ligne ?)")

    correspond, dist = await visage_correspond(face_row.encoding, encoding_actuel, seuil=seuil)

    if not correspond:
        await manager.broadcast({
            "event": "acces_refuse",
            "reason": "visage_non_reconnu",
            "employe_id": employe.id,
            "distance": round(dist, 4),
            "message": "Accès refusé : visage non reconnu.",
        })
        return {
            "result": "DENIED",
            "reason": "visage_non_reconnu",
            "employe_id": employe.id,
            "distance": round(dist, 4),
        }

    aujourdhui = date.today()
    heure_actuelle = datetime.now().time()

    if not carte.isentree:
        action = "entree"
        entree = PresenceEntree(id_employe=employe.id, date=aujourdhui, heure_entree=heure_actuelle, ack=True)
        carte.isentree = True

        presence = (
            await db.execute(
                select(Presence).where(Presence.id_employe == employe.id, Presence.datedujour == aujourdhui)
            )
        ).scalar_one_or_none()
        if not presence:
            presence = Presence(id_employe=employe.id, datedujour=aujourdhui, statut="present")
            db.add(presence)
        db.add(entree)
        message = f"{employe.nom} est entré dans l'entreprise."
    else:
        action = "sortie"
        sortie = Sortie(id_employe=employe.id, date=aujourdhui, heure_sortie=heure_actuelle)
        carte.isentree = False
        db.add(sortie)
        message = f"{employe.nom} est sorti de l'entreprise."

    await db.commit()

    await manager.broadcast({
        "event": f"{action}_entreprise",
        "message": message,
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "biometrie",
    })

    return {
        "result": "AUTHORIZED",
        "action": action,
        "employe_id": employe.id,
        "nom": employe.nom,
        "distance": round(dist, 4),
        "heure": heure_actuelle.strftime("%H:%M:%S"),
    }


@router.delete("/{employe_id}", dependencies=[Depends(require_admin)])
async def supprimer_visage(employe_id: int, db: AsyncSession = Depends(get_db)):
    supprime = await nettoyer_biometrie_employe(db, employe_id)
    await db.commit()
    if not supprime:
        raise HTTPException(404, "Aucun encoding enregistré pour cet employé")
    return {"success": True, "message": "Encoding facial supprimé"}