# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.core.supabase_client import supabase
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import Candidat, Employe
from app.schemas.schemas import LinkEmployeRequest, RegisterRequest, UserAuth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Crée le compte Supabase ET le profil candidat associé en une seule étape.
    Le `nom` saisi ici sert directement de nom de candidat (puis d'employé
    si le candidat est accepté plus tard) : pas de ressaisie nécessaire.
    """
    try:
        response = supabase.auth.sign_up({
            "email": payload.email,
            "password": payload.password,
            "options": {"data": {"role": "user", "nom": payload.nom}},
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = response.user
    if not user:
        raise HTTPException(status_code=400, detail="Échec de la création du compte")

    # Empêche les doublons de parcours (même nom déjà en attente ou actif)
    nom_norm = " ".join(payload.nom.strip().lower().split())
    existant = (
        await db.execute(
            select(Candidat).where(
                func.lower(func.trim(Candidat.nom)) == nom_norm,
                Candidat.statut.in_(["attente", "actif"]),
            )
        )
    ).scalar_one_or_none()

    if existant:
        raise HTTPException(
            status_code=409,
            detail="Un parcours est déjà en cours avec ce nom. Connecte-toi ou attends la fin de ton parcours.",
        )

    candidat = Candidat(
        nom=payload.nom.strip(),
        statut="attente",
        user_id=user.id,
    )
    db.add(candidat)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Compte créé mais échec de la création du profil candidat. Réessaie /auth/login puis contacte un admin.",
        )
    await db.refresh(candidat)

    await manager.broadcast({
        "event": "inscription",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
    })

    return {
        "success": True,
        "user": user,
        "candidat": {"id": candidat.id, "nom": candidat.nom, "statut": candidat.statut},
    }


@router.post("/login")
def login(user: UserAuth):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password,
        })
        return {
            "success": True,
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "user": response.user,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/link-employe")
async def link_employe(
    payload: LinkEmployeRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Conservé pour les employés créés manuellement (POST /employes, sans passer
    par un candidat) : permet de lier après coup un compte à un matricule existant.
    """
    # 1. Le compte est-il déjà lié à un employé ?
    deja_lie = (
        await db.execute(select(Employe).where(Employe.user_id == user.id))
    ).scalar_one_or_none()
    if deja_lie:
        raise HTTPException(409, "Ce compte est déjà lié à un employé")

    # 2. Trouver l'employé par matricule
    employe = (
        await db.execute(select(Employe).where(Employe.matricule == payload.matricule))
    ).scalar_one_or_none()
    if not employe:
        raise HTTPException(404, "Aucun employé avec ce matricule")

    # 3. Cet employé est-il déjà lié à un autre compte ?
    if employe.user_id is not None:
        raise HTTPException(409, "Cet employé est déjà lié à un compte")

    # 4. Lier
    employe.user_id = user.id
    await db.commit()
    await db.refresh(employe)

    return {
        "success": True,
        "message": "Compte lié à l'employé avec succès",
        "employe": {
            "id": employe.id,
            "nom": employe.nom,
            "prenom": employe.prenom,
            "matricule": employe.matricule,
        },
    }