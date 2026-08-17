from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.database import get_db
from app.db.models import Employe
from app.schemas.schemas import EmployeCreate, EmployeOut, EmployeUpdate

router = APIRouter(prefix="/employes", tags=["employes"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[EmployeOut])
async def list_employes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Employe))
    return result.scalars().all()


@router.get("/{employe_id}", response_model=EmployeOut)
async def get_employe(employe_id: int, db: AsyncSession = Depends(get_db)):
    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")
    return employe


@router.post("", response_model=EmployeOut, status_code=201)
async def create_employe(payload: EmployeCreate, db: AsyncSession = Depends(get_db)):
    employe = Employe(**payload.model_dump())
    db.add(employe)
    await db.commit()
    await db.refresh(employe)
    return employe


@router.patch("/{employe_id}", response_model=EmployeOut)
async def update_employe(
    employe_id: int,
    payload: EmployeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")

    update_data = payload.model_dump(exclude_unset=True)

    # Lier/délier un compte Supabase à un employé = réservé aux admins
    if "user_id" in update_data:
        if current_user.role != "admin":
            raise HTTPException(403, "Seul un administrateur peut lier un compte à un employé")

        new_user_id = update_data["user_id"]
        if new_user_id is not None:
            deja_lie = (
                await db.execute(select(Employe).where(Employe.user_id == new_user_id))
            ).scalar_one_or_none()
            if deja_lie and deja_lie.id != employe.id:
                raise HTTPException(409, "Ce compte est déjà lié à un autre employé")

    # Assigner une carte RFID à un employé qui n'en avait pas encore
    # (cas typique : employé promu depuis un candidat, carte reçue plus tard).
    if "carterfid_id" in update_data and update_data["carterfid_id"] is not None:
        deja_prise = (
            await db.execute(
                select(Employe).where(Employe.carterfid_id == update_data["carterfid_id"])
            )
        ).scalar_one_or_none()
        if deja_prise and deja_prise.id != employe.id:
            raise HTTPException(409, "Cette carte est déjà assignée à un autre employé")

    for field, value in update_data.items():
        setattr(employe, field, value)

    await db.commit()
    await db.refresh(employe)
    return employe
    
    
@router.delete("/{employe_id}", status_code=204)
async def delete_employe(employe_id: int, db: AsyncSession = Depends(get_db)):
    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")
    await db.delete(employe)
    await db.commit()
