import random

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import delete, select, update
from app.core.security import require_admin
from app.db.database import get_db
from app.db.models import Candidat, Employe, Poste
from app.schemas.schemas import CandidatInscription, CandidatOut
from app.core.biometrie_hooks import nettoyer_biometrie_employe
from datetime import date, datetime, timezone
from sqlalchemy import func
from app.core.ws_manager import manager

router = APIRouter(prefix="/candidats", tags=["candidats"])
limiter = Limiter(key_func=get_remote_address)

# --- Public : inscription visiteur ---

@router.post("/inscription", response_model=CandidatOut, status_code=201)
@limiter.limit("1/20seconds")
async def inscription(
    request: Request,
    payload: CandidatInscription,
    db: AsyncSession = Depends(get_db),
):
    nom = payload.nom.strip()
    if not nom or len(nom) > 50:
        raise HTTPException(400, "Nom invalide")

    # Normalisation simple (insensible à la casse + espaces)
    nom_norm = " ".join(nom.lower().split())

    # Vérifier s’il existe déjà un candidat "en cours" avec ce nom
    existant = (
        await db.execute(
            select(Candidat).where(
                func.lower(func.trim(Candidat.nom)) == nom_norm,
                Candidat.statut.in_(["attente", "actif"]),
            )
        )
    ).scalar_one_or_none()

    if existant:
        # On renvoie l’existant au lieu d’en créer un nouveau
        # (le front peut afficher "Tu es déjà inscrit, voici ton statut")
        return existant

    candidat = Candidat(
        nom=nom,
        statut="attente",
        ip_inscription=get_remote_address(request),
    )
    db.add(candidat)
    await db.commit()
    await db.refresh(candidat)

    await manager.broadcast({
        "event": "inscription",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
    })
    return candidat


@router.get("/mon-statut", response_model=CandidatOut)
async def mon_statut(candidat_id: int, db: AsyncSession = Depends(get_db)):
    """Le visiteur consulte son propre statut avec l'id reçu à l'inscription."""
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    return candidat


# --- Admin uniquement ---

@router.get("", response_model=list[CandidatOut], dependencies=[Depends(require_admin)])
async def liste_candidats(db: AsyncSession = Depends(get_db)):
    stmt = select(Candidat).where(Candidat.statut != "historique").order_by(Candidat.heure_inscription)
    return (await db.execute(stmt)).scalars().all()


@router.get("/historique", response_model=list[CandidatOut], dependencies=[Depends(require_admin)])
async def historique(db: AsyncSession = Depends(get_db)):
    stmt = select(Candidat).where(Candidat.statut == "historique").order_by(Candidat.heure_retrait.desc())
    return (await db.execute(stmt)).scalars().all()


def _generer_matricule(candidat_id: int) -> str:
    """Matricule auto pour les employés promus depuis un candidat."""
    return f"CAND-{candidat_id:06d}"


@router.post("/{candidat_id}/virer", response_model=CandidatOut, dependencies=[Depends(require_admin)])
async def virer_manuellement(candidat_id: int, db: AsyncSession = Depends(get_db)):
    """
    Vire manuellement un candidat/employé (sans passer par la simulation).

    - Passe le candidat en "historique"
    - Passe l'employé en "Inactif"
    - Détache la carte RFID
    - Broadcast l'événement
    """
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")

    if candidat.statut not in ("actif", "attente"):
        raise HTTPException(409, "Ce candidat n'est plus actif ou en attente")

    # On récupère l'employé s'il existe
    employe = None
    if candidat.employe_id:
        employe = await db.get(Employe, candidat.employe_id)

    # 1. Candidat → historique
    candidat.statut = "historique"
    candidat.heure_retrait = datetime.now(timezone.utc)

    # 2. Employé → Inactif + détacher la carte
    if employe:
        employe.status = "Inactif"
        employe.carterfid_id = None          # libère la carte
        await nettoyer_biometrie_employe(db, employe.id)
        
    await db.commit()
    await db.refresh(candidat)

    # 3. Broadcast
    await manager.broadcast({
        "event": "vire_manuel",
        "message": f"{candidat.nom} a été viré manuellement.",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "employe_id": employe.id if employe else None,
    })

    return candidat

@router.post("/{candidat_id}/accepter", response_model=CandidatOut, dependencies=[Depends(require_admin)])
async def accepter(candidat_id: int, db: AsyncSession = Depends(get_db)):
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "attente":
        raise HTTPException(409, "Ce candidat n'est pas en attente")

    # On vérifie qu'il n'y a pas déjà un candidat actif
    deja_actif = (
        await db.execute(select(Candidat).where(Candidat.statut == "actif"))
    ).scalar_one_or_none()
    if deja_actif:
        raise HTTPException(409, "Un candidat est déjà actif, retire-le d'abord")

    candidat.statut = "actif"
    candidat.heure_acceptation = datetime.now(timezone.utc)

    # L'employé est créé MAINTENANT, sans poste ni carte : ça permet au
    # téléphone du visiteur d'enrôler son visage juste après (l'enrôlement
    # a besoin d'un employe_id valide). La roulette (attribution du poste)
    # se déclenche à la fin de l'enrôlement, voir
    # app/routers/biometrie.py::enroll_visage.
    employe = Employe(
        nom=candidat.nom,
        matricule=_generer_matricule(candidat.id),
        id_poste=None,
        carterfid_id=None,
        status="Actif",
        user_id=candidat.user_id,
        date_embauche=date.today(),
    )
    db.add(employe)
    await db.flush()
    candidat.employe_id = employe.id

    await db.commit()
    await db.refresh(candidat)

    await manager.broadcast({
        "event": "candidat_actif",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "employe_id": employe.id,
        "message": "Veuillez enregistrer votre visage pour devenir employé.",
    })

    return candidat

@router.post("/{candidat_id}/retirer", response_model=CandidatOut, dependencies=[Depends(require_admin)])
async def retirer(candidat_id: int, db: AsyncSession = Depends(get_db)):
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "actif":
        raise HTTPException(409, "Ce candidat n'est pas actif")

    # Ne touche qu'au statut du candidat : l'employé créé lors de
    # l'acceptation (candidat.employe_id) reste intact dans la table employes.
    candidat.statut = "historique"
    candidat.heure_retrait = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(candidat)
    await manager.broadcast({"event": "retrait", "candidat_id": candidat.id})
    return candidat


@router.post("/vider-attente", dependencies=[Depends(require_admin)])
async def vider_attente(db: AsyncSession = Depends(get_db)):
    """Bouton panique : personne ne répond, on relance tout le monde."""
    await db.execute(
        update(Candidat).where(Candidat.statut == "attente").values(statut="historique")
    )
    await db.commit()
    return {"message": "File d'attente vidée"}

@router.delete("/{candidat_id}", status_code=204, dependencies=[Depends(require_admin)])
async def supprimer_candidat(candidat_id: int, db: AsyncSession = Depends(get_db)):
    """Supprime un candidat, peu importe son statut (spam, nom déplacé, etc.).
    N'efface pas l'employé éventuellement déjà créé (employe_id)."""
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    await db.delete(candidat)
    await db.commit()


@router.delete("/attente/tout", dependencies=[Depends(require_admin)])
async def supprimer_toute_attente(db: AsyncSession = Depends(get_db)):
    """Vide complètement la file d'attente (différent de vider-attente qui archive)."""
    result = await db.execute(delete(Candidat).where(Candidat.statut == "attente"))
    await db.commit()
    return {"message": f"{result.rowcount} candidat(s) supprimé(s)"}

@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats(db: AsyncSession = Depends(get_db)):
    en_attente = (await db.execute(
        select(func.count()).select_from(Candidat).where(Candidat.statut == "attente")
    )).scalar()
    deja_passes = (await db.execute(
        select(func.count()).select_from(Candidat).where(Candidat.statut == "historique")
    )).scalar()
    return {"en_attente": en_attente, "deja_passes": deja_passes}
