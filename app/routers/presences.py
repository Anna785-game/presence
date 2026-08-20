from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_admin
from app.core.time_utils import aujourdhui as _aujourdhui, maintenant as _maintenant
from app.db.database import get_db
from app.db.models import Absence, Employe, Presence, PresenceEntree, Sortie
from app.schemas.schemas import AbsenceCreate, AbsenceOut, PresenceOut

router = APIRouter(tags=["presences"], dependencies=[Depends(get_current_user)])


@router.get("/presences", response_model=list[PresenceOut])
async def list_presences(
    employe_id: int | None = None,
    jour: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Presence)
    if employe_id:
        stmt = stmt.where(Presence.id_employe == employe_id)
    if jour:
        stmt = stmt.where(Presence.datedujour == jour)
    return (await db.execute(stmt)).scalars().all()


@router.get("/absences", response_model=list[AbsenceOut])
async def list_absences(employe_id: int | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Absence)
    if employe_id:
        stmt = stmt.where(Absence.idemploye == employe_id)
    return (await db.execute(stmt)).scalars().all()


@router.post("/absences", response_model=AbsenceOut, status_code=201)
async def create_absence(payload: AbsenceCreate, db: AsyncSession = Depends(get_db)):
    absence = Absence(**payload.model_dump())
    db.add(absence)
    await db.commit()
    await db.refresh(absence)
    return absence


# ---------------------------------------------------------------------------
# Équivalents des commandes Symfony `app:calcul-duree-travail` et
# `app:insert-absence`. À appeler depuis un scheduler (cron / pg_cron /
# Supabase Edge Function planifiée) plutôt que manuellement en prod.
# Protégés par require_admin pour éviter un déclenchement non désiré.
# ---------------------------------------------------------------------------


@router.post("/jobs/calcul-duree-travail")
async def calcul_duree_travail(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    today = _aujourdhui()
    employes = (
        await db.execute(select(Employe).where(Employe.status == "Actif"))
    ).scalars().all()

    count = 0
    for employe in employes:
        entrees = (
            await db.execute(
                select(PresenceEntree).where(
                    PresenceEntree.id_employe == employe.id, PresenceEntree.date == today
                )
            )
        ).scalars().all()
        sorties = (
            await db.execute(
                select(Sortie).where(Sortie.id_employe == employe.id, Sortie.date == today)
            )
        ).scalars().all()

        if not entrees or not sorties:
            continue

        entrees.sort(key=lambda e: e.heure_entree)
        sorties.sort(key=lambda s: s.heure_sortie)

        total_minutes = 0
        for e, s in zip(entrees, sorties):
            entree_dt = datetime.combine(today, e.heure_entree)
            sortie_dt = datetime.combine(today, s.heure_sortie)
            total_minutes += max(0, int((sortie_dt - entree_dt).total_seconds() // 60))

        presence = (
            await db.execute(
                select(Presence).where(
                    Presence.id_employe == employe.id, Presence.datedujour == today
                )
            )
        ).scalar_one_or_none()

        if not presence:
            presence = Presence(id_employe=employe.id, datedujour=today, statut="ok")
            db.add(presence)

        presence.dureetravail = total_minutes
        count += 1

    await db.commit()
    return {"message": f"Durée calculée pour {count} employé(s)"}


@router.post("/jobs/insert-absences")
async def insert_absences(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    today = _aujourdhui()
    employes = (
        await db.execute(select(Employe).where(Employe.status == "Actif"))
    ).scalars().all()

    count = 0
    for employe in employes:
        presence = (
            await db.execute(
                select(Presence).where(
                    Presence.id_employe == employe.id, Presence.datedujour == today
                )
            )
        ).scalar_one_or_none()

        if not presence:
            db.add(Absence(idemploye=employe.id, dateabsence=today, raison="Non justifiée"))
            count += 1

    await db.commit()
    return {"message": f"{count} absence(s) ajoutée(s)"}
