# app/routers/cartes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import Carterfid, Candidat, Employe
from app.schemas.schemas import CarterfidCreate, CarterfidOut

router = APIRouter(
    prefix="/cartes",
    tags=["cartes"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[CarterfidOut])
async def list_cartes(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Carterfid))).scalars().all()


@router.post("", response_model=CarterfidOut, status_code=201)
async def create_carte(payload: CarterfidCreate, db: AsyncSession = Depends(get_db)):
    carte = Carterfid(**payload.model_dump(), isentree=False)
    db.add(carte)
    await db.commit()
    await db.refresh(carte)

    await manager.broadcast({
        "event": "carte_creee",
        "carte_id": carte.id,
        "carte_uid": carte.uidcarte,
        "message": f"Carte {carte.uidcarte} ajoutée manuellement.",
    })

    return carte


@router.delete("/{carte_id}", status_code=204)
async def delete_carte(carte_id: int, db: AsyncSession = Depends(get_db)):
    carte = await db.get(Carterfid, carte_id)
    if not carte:
        raise HTTPException(404, "Carte non trouvée")
    # Refuser si déjà assignée
    deja = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if deja:
        raise HTTPException(409, "Cette carte est encore assignée à un employé")
    uid = carte.uidcarte
    await db.delete(carte)
    await db.commit()

    await manager.broadcast({
        "event": "carte_supprimee",
        "carte_id": carte_id,
        "carte_uid": uid,
        "message": f"Carte {uid} supprimée.",
    })


@router.get("/en-attente")
async def cartes_en_attente(db: AsyncSession = Depends(get_db)):
    """
    Employés qui ont terminé enrôlement + choix de poste,
    mais n'ont pas encore de carte RFID.
    """
    stmt = (
        select(Candidat, Employe)
        .join(Employe, Employe.id == Candidat.employe_id)
        .where(
            Candidat.statut == "actif",
            Candidat.employe_id.is_not(None),
            Candidat.poste_attribue.is_not(None),
            Employe.carterfid_id.is_(None),
            Employe.status == "Actif",
        )
        .order_by(Candidat.heure_acceptation)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "candidat_id": c.id,
            "employe_id": e.id,
            "nom": c.nom,
            "poste": c.poste_attribue,
            "matricule": e.matricule,
        }
        for c, e in rows
    ]


@router.get("/disponibles", response_model=list[CarterfidOut])
async def cartes_disponibles(db: AsyncSession = Depends(get_db)):
    """Cartes RFID non encore liées à un employé."""
    subq = select(Employe.carterfid_id).where(Employe.carterfid_id.is_not(None))
    stmt = select(Carterfid).where(Carterfid.id.not_in(subq)).order_by(Carterfid.id)
    return (await db.execute(stmt)).scalars().all()


@router.post("/attribuer")
async def attribuer_carte_admin(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Body: { "employe_id": int, "carterfid_id": int }
    L'admin choisit une carte libre et la remet physiquement au candidat.
    """
    employe_id = payload.get("employe_id")
    carterfid_id = payload.get("carterfid_id")
    if not employe_id or not carterfid_id:
        raise HTTPException(400, "employe_id et carterfid_id requis")

    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé introuvable")
    if employe.status != "Actif":
        raise HTTPException(409, "Cet employé n'est plus actif")
    if employe.carterfid_id is not None:
        raise HTTPException(409, "Cet employé a déjà une carte")

    carte = await db.get(Carterfid, carterfid_id)
    if not carte:
        raise HTTPException(404, "Carte introuvable")

    deja = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if deja:
        raise HTTPException(409, "Cette carte est déjà assignée à un autre employé")

    employe.carterfid_id = carte.id
    await db.commit()

    candidat = (
        await db.execute(select(Candidat).where(Candidat.employe_id == employe.id))
    ).scalar_one_or_none()

    nom = candidat.nom if candidat else (employe.nom or f"#{employe.id}")

    await manager.broadcast({
        "event": "carte_assignee",
        "employe_id": employe.id,
        "carte_uid": carte.uidcarte,
        "candidat": {"id": candidat.id, "nom": candidat.nom} if candidat else None,
        "message": f"Carte {carte.uidcarte} remise à {nom}.",
    })

    return {
        "success": True,
        "employe_id": employe.id,
        "carte_uid": carte.uidcarte,
        "nom": nom,
    }
