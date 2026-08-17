from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Poste
from app.schemas.schemas import PosteCreate, PosteOut
from app.core.security import get_current_user, require_admin

router = APIRouter(prefix="/postes", tags=["postes"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[PosteOut])
async def list_postes(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Poste))).scalars().all()


@router.post("", response_model=PosteOut, status_code=201)
async def create_poste(payload: PosteCreate, db: AsyncSession = Depends(get_db)):
    poste = Poste(**payload.model_dump())
    db.add(poste)
    await db.commit()
    await db.refresh(poste)
    return poste


@router.delete("/{poste_id}", status_code=204)
async def delete_poste(poste_id: int, db: AsyncSession = Depends(get_db)):
    poste = await db.get(Poste, poste_id)
    if not poste:
        raise HTTPException(404, "Poste non trouvé")
    await db.delete(poste)
    await db.commit()

@router.post("/seed-demo", response_model=list[PosteOut], dependencies=[Depends(require_admin)])
async def seed_postes_demo(db: AsyncSession = Depends(get_db)):
    """Remplit la table avec les postes fun pour la roulette. À appeler une fois avant l'expo."""
    postes_demo = [
        ("Nettoyeur de toilettes", 40),
        ("Boss", 30),
        ("Vendeur", 30),
    ]
    existants = {p.type_poste for p in (await db.execute(select(Poste))).scalars().all()}
    crees = []
    for nom, poids in postes_demo:
        if nom not in existants:
            p = Poste(type_poste=nom, poids=poids)
            db.add(p)
            crees.append(p)
    await db.commit()
    for p in crees:
        await db.refresh(p)
    return crees
