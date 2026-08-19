"""
À intégrer dans app/routers/presences.py (ou créer un nouveau router
et l'inclure dans main.py).

Ajoute :
  GET  /presences/live          → qui est actuellement dans l'entreprise
  POST /presences/force-sortie/{employe_id}  → admin force une sortie
  GET  /employes/{id}/parcours  → timeline complète (à coller aussi dans employes.py
                                   ou ici si tu préfères un seul fichier)

Schemas Pydantic à ajouter dans app/schemas/schemas.py (voir en bas).
"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_admin
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import (
    Absence,
    Carterfid,
    Employe,
    Presence,
    PresenceEntree,
    Sortie,
)

router = APIRouter(tags=["presences"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Schemas (à mettre aussi dans schemas.py si tu préfères)
# ---------------------------------------------------------------------------

class PresentLiveOut(BaseModel):
    employe_id: int
    nom: str | None
    prenom: str | None
    matricule: str
    id_poste: int | None
    heure_entree: str          # HH:MM:SS
    minutes_depuis: int        # temps passé depuis l'entrée
    uidcarte: str | None


class ParcoursEvent(BaseModel):
    type: str                  # "entree" | "sortie" | "absence" | "presence_jour"
    date: str                  # YYYY-MM-DD
    heure: str | None = None   # HH:MM:SS
    duree_minutes: int | None = None
    label: str
    detail: str | None = None


class ParcoursOut(BaseModel):
    employe_id: int
    nom: str | None
    prenom: str | None
    matricule: str
    status: str | None
    id_poste: int | None
    is_present: bool
    timeline: list[ParcoursEvent]
    durees_par_jour: list[dict]   # [{date, duree_minutes}] pour le graphique


# ---------------------------------------------------------------------------
# GET /presences/live
# ---------------------------------------------------------------------------

@router.get("/presences/live", response_model=list[PresentLiveOut])
async def liste_presents_live(db: AsyncSession = Depends(get_db)):
    """
    Employés actuellement présents = carte.isentree == True et status Actif.
    On joint la dernière entrée du jour pour afficher l'heure d'entrée.
    """
    aujourdhui = date.today()
    maintenant = datetime.now()

    # Cartes marquées "entrées"
    cartes = (
        await db.execute(
            select(Carterfid).where(Carterfid.isentree == True)  # noqa: E712
        )
    ).scalars().all()

    result: list[PresentLiveOut] = []
    for carte in cartes:
        employe = (
            await db.execute(
                select(Employe).where(
                    Employe.carterfid_id == carte.id,
                    Employe.status == "Actif",
                )
            )
        ).scalar_one_or_none()
        if not employe:
            continue

        derniere_entree = (
            await db.execute(
                select(PresenceEntree)
                .where(
                    PresenceEntree.id_employe == employe.id,
                    PresenceEntree.date == aujourdhui,
                )
                .order_by(PresenceEntree.heure_entree.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if not derniere_entree:
            # Incohérence (isentree=True mais pas d'entrée du jour) → on ignore
            continue

        entree_dt = datetime.combine(aujourdhui, derniere_entree.heure_entree)
        minutes = max(0, int((maintenant - entree_dt).total_seconds() // 60))

        result.append(
            PresentLiveOut(
                employe_id=employe.id,
                nom=employe.nom,
                prenom=employe.prenom,
                matricule=employe.matricule,
                id_poste=employe.id_poste,
                heure_entree=derniere_entree.heure_entree.strftime("%H:%M:%S"),
                minutes_depuis=minutes,
                uidcarte=carte.uidcarte,
            )
        )

    # Tri : plus long présent en premier
    result.sort(key=lambda x: x.minutes_depuis, reverse=True)
    return result


# ---------------------------------------------------------------------------
# POST /presences/force-sortie/{employe_id}
# ---------------------------------------------------------------------------

@router.post("/presences/force-sortie/{employe_id}", dependencies=[Depends(require_admin)])
async def force_sortie(employe_id: int, db: AsyncSession = Depends(get_db)):
    """Admin force la sortie d'un employé (oubli de badger)."""
    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")
    if not employe.carterfid_id:
        raise HTTPException(400, "Cet employé n'a pas de carte RFID")

    carte = await db.get(Carterfid, employe.carterfid_id)
    if not carte or not carte.isentree:
        raise HTTPException(409, "Cet employé n'est pas marqué présent")

    aujourdhui = date.today()
    heure_actuelle = datetime.now().time()

    sortie = Sortie(
        id_employe=employe.id,
        date=aujourdhui,
        heure_sortie=heure_actuelle,
    )
    carte.isentree = False
    db.add(sortie)

    # Durée depuis dernière entrée
    derniere_entree = (
        await db.execute(
            select(PresenceEntree)
            .where(
                PresenceEntree.id_employe == employe.id,
                PresenceEntree.date == aujourdhui,
            )
            .order_by(PresenceEntree.heure_entree.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    duree_minutes = None
    heure_entree_str = None
    if derniere_entree:
        heure_entree_str = derniere_entree.heure_entree.strftime("%H:%M:%S")
        entree_dt = datetime.combine(aujourdhui, derniere_entree.heure_entree)
        sortie_dt = datetime.combine(aujourdhui, heure_actuelle)
        duree_minutes = max(0, int((sortie_dt - entree_dt).total_seconds() // 60))

        presence = (
            await db.execute(
                select(Presence).where(
                    Presence.id_employe == employe.id,
                    Presence.datedujour == aujourdhui,
                )
            )
        ).scalar_one_or_none()
        if presence:
            presence.dureetravail = (presence.dureetravail or 0) + duree_minutes
        else:
            db.add(
                Presence(
                    id_employe=employe.id,
                    datedujour=aujourdhui,
                    statut="present",
                    dureetravail=duree_minutes,
                )
            )

    await db.commit()

    await manager.broadcast({
        "event": "sortie_entreprise",
        "message": f"{employe.nom} a été sorti manuellement par l'admin.",
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "force_admin",
        "heure": heure_actuelle.strftime("%H:%M:%S"),
        "heure_entree": heure_entree_str,
        "duree_minutes": duree_minutes,
    })

    return {
        "success": True,
        "employe_id": employe.id,
        "heure_sortie": heure_actuelle.strftime("%H:%M:%S"),
        "heure_entree": heure_entree_str,
        "duree_minutes": duree_minutes,
    }


# ---------------------------------------------------------------------------
# GET /employes/{employe_id}/parcours
# (à coller dans employes.py de préférence, ou garder ici)
# ---------------------------------------------------------------------------

@router.get("/employes/{employe_id}/parcours", response_model=ParcoursOut)
async def parcours_employe(employe_id: int, db: AsyncSession = Depends(get_db)):
    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")

    # Présent ?
    is_present = False
    if employe.carterfid_id:
        carte = await db.get(Carterfid, employe.carterfid_id)
        is_present = bool(carte and carte.isentree)

    # Entrées
    entrees = (
        await db.execute(
            select(PresenceEntree)
            .where(PresenceEntree.id_employe == employe_id)
            .order_by(PresenceEntree.date.desc(), PresenceEntree.heure_entree.desc())
        )
    ).scalars().all()

    # Sorties
    sorties = (
        await db.execute(
            select(Sortie)
            .where(Sortie.id_employe == employe_id)
            .order_by(Sortie.date.desc(), Sortie.heure_sortie.desc())
        )
    ).scalars().all()

    # Absences
    absences = (
        await db.execute(
            select(Absence)
            .where(Absence.idemploye == employe_id)
            .order_by(Absence.dateabsence.desc())
        )
    ).scalars().all()

    # Présences (durée journalière)
    presences = (
        await db.execute(
            select(Presence)
            .where(Presence.id_employe == employe_id)
            .order_by(Presence.datedujour.desc())
        )
    ).scalars().all()

    timeline: list[ParcoursEvent] = []

    for e in entrees:
        timeline.append(
            ParcoursEvent(
                type="entree",
                date=e.date.isoformat(),
                heure=e.heure_entree.strftime("%H:%M:%S"),
                label=f"Entrée à {e.heure_entree.strftime('%H:%M')}",
            )
        )

    for s in sorties:
        # Essaie de trouver l'entrée correspondante du même jour pour la durée
        duree = None
        candidates = [e for e in entrees if e.date == s.date and e.heure_entree <= s.heure_sortie]
        if candidates:
            best = max(candidates, key=lambda x: x.heure_entree)
            entree_dt = datetime.combine(s.date, best.heure_entree)
            sortie_dt = datetime.combine(s.date, s.heure_sortie)
            duree = max(0, int((sortie_dt - entree_dt).total_seconds() // 60))

        timeline.append(
            ParcoursEvent(
                type="sortie",
                date=s.date.isoformat(),
                heure=s.heure_sortie.strftime("%H:%M:%S"),
                duree_minutes=duree,
                label=f"Sortie à {s.heure_sortie.strftime('%H:%M')}"
                + (f" ({duree // 60}h{duree % 60:02d})" if duree is not None else ""),
            )
        )

    for a in absences:
        timeline.append(
            ParcoursEvent(
                type="absence",
                date=a.dateabsence.isoformat(),
                label="Absence",
                detail=a.raison,
            )
        )

    # Tri chronologique inverse (plus récent en premier)
    timeline.sort(key=lambda ev: (ev.date, ev.heure or "00:00:00"), reverse=True)

    durees_par_jour = [
        {
            "date": p.datedujour.isoformat(),
            "duree_minutes": p.dureetravail or 0,
            "statut": p.statut,
        }
        for p in presences
        if p.dureetravail is not None
    ]

    return ParcoursOut(
        employe_id=employe.id,
        nom=employe.nom,
        prenom=employe.prenom,
        matricule=employe.matricule,
        status=employe.status,
        id_poste=employe.id_poste,
        is_present=is_present,
        timeline=timeline,
        durees_par_jour=durees_par_jour,
    )
