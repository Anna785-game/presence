from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Carterfid
from app.schemas.schemas import CarterfidCreate, CarterfidOut

router = APIRouter(prefix="/cartes", tags=["cartes"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[CarterfidOut])
async def list_cartes(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Carterfid))).scalars().all()


@router.post("", response_model=CarterfidOut, status_code=201)
async def create_carte(payload: CarterfidCreate, db: AsyncSession = Depends(get_db)):
    carte = Carterfid(**payload.model_dump(), isentree=False)
    db.add(carte)
    await db.commit()
    await db.refresh(carte)
    return carte


@router.delete("/{carte_id}", status_code=204)
async def delete_carte(carte_id: int, db: AsyncSession = Depends(get_db)):
    carte = await db.get(Carterfid, carte_id)
    if not carte:
        raise HTTPException(404, "Carte non trouvée")
    await db.delete(carte)
    await db.commit()
