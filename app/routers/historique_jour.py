"""
GET /historique/jour?date=YYYY-MM-DD

Agrège, pour une journée donnée, tous les employés ayant un événement :
  - présence (entrée / sortie / durée)
  - absence
  - licenciement (candidat.heure_retrait le même jour civil, ou statut Inactif
    + absence raison "Viré" créée par POST /employes/{id}/virer)

Un employé n'apparaît que s'il a au moins un de ces événements ce jour-là.
S'il est viré le 21, il n'apparaît plus le 22 (sauf s'il a encore une
ligne d'absence/présence ce jour-là, ce qui ne devrait pas arriver).

À monter dans main.py :
    from app.routers.historique_jour import router as historique_jour_router
    app.include_router(historique_jour_router)
"""

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_admin
from app.core.ws_manager import manager
from app.core.biometrie_hooks import nettoyer_biometrie_employe
from app.db.database import get_db
from app.db.models import (
    Absence,
    Candidat,
    Employe,
    Poste,
    Presence,
    PresenceEntree,
    Sortie,
)

router = APIRouter(tags=["historique"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EvenementJour(BaseModel):
    type: str  # "entree" | "sortie"
    heure: str | None = None
    duree_minutes: int | None = None
    label: str


class EmployeJourOut(BaseModel):
    employe_id: int
    nom: str | None
    prenom: str | None
    matricule: str | None
    poste: str | None
    statut_jour: str  # "present" | "absent" | "vire"
    heure_entree: str | None = None
    heure_sortie: str | None = None
    duree_minutes: int | None = None
    raison: str | None = None
    evenements: list[EvenementJour] = []


class HistoriqueJourOut(BaseModel):
    date: str
    employes: list[EmployeJourOut]


# ---------------------------------------------------------------------------
# GET /historique/jour
# ---------------------------------------------------------------------------

@router.get("/historique/jour", response_model=HistoriqueJourOut)
async def historique_jour(
    date_jour: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    # --- Présences du jour -------------------------------------------------
    presences = (
        await db.execute(
            select(Presence).where(Presence.datedujour == date_jour)
        )
    ).scalars().all()
    presence_by_emp = {p.id_employe: p for p in presences}

    entrees = (
        await db.execute(
            select(PresenceEntree).where(PresenceEntree.date == date_jour)
        )
    ).scalars().all()
    sorties = (
        await db.execute(
            select(Sortie).where(Sortie.date == date_jour)
        )
    ).scalars().all()

    entrees_by_emp: dict[int, list] = {}
    for e in entrees:
        entrees_by_emp.setdefault(e.id_employe, []).append(e)
    sorties_by_emp: dict[int, list] = {}
    for s in sorties:
        sorties_by_emp.setdefault(s.id_employe, []).append(s)

    # --- Absences du jour --------------------------------------------------
    absences = (
        await db.execute(
            select(Absence).where(Absence.dateabsence == date_jour)
        )
    ).scalars().all()
    absence_by_emp = {a.idemploye: a for a in absences}

    # --- Licenciements ce jour (via candidat.heure_retrait) ----------------
    debut = datetime.combine(date_jour, time.min, tzinfo=timezone.utc)
    fin = debut + timedelta(days=1)
    candidats_vires = (
        await db.execute(
            select(Candidat).where(
                Candidat.heure_retrait >= debut,
                Candidat.heure_retrait < fin,
                Candidat.employe_id.is_not(None),
            )
        )
    ).scalars().all()
    vire_by_emp = {c.employe_id: c for c in candidats_vires if c.employe_id}

    # Aussi : absences dont la raison commence par "Viré" (créées par /virer)
    for a in absences:
        if a.raison and a.raison.lower().startswith("viré"):
            vire_by_emp.setdefault(a.idemploye, None)

    emp_ids = set(presence_by_emp) | set(entrees_by_emp) | set(sorties_by_emp) | set(absence_by_emp) | set(vire_by_emp)
    if not emp_ids:
        return HistoriqueJourOut(date=date_jour.isoformat(), employes=[])

    employes = (
        await db.execute(select(Employe).where(Employe.id.in_(emp_ids)))
    ).scalars().all()
    emp_map = {e.id: e for e in employes}

    postes = (await db.execute(select(Poste))).scalars().all()
    poste_map = {p.id: p.type_poste for p in postes}

    result: list[EmployeJourOut] = []
    for eid in emp_ids:
        emp = emp_map.get(eid)
        if not emp:
            continue

        is_vire = eid in vire_by_emp
        abs_row = absence_by_emp.get(eid)
        pres = presence_by_emp.get(eid)
        ents = sorted(entrees_by_emp.get(eid, []), key=lambda x: x.heure_entree)
        sorts = sorted(sorties_by_emp.get(eid, []), key=lambda x: x.heure_sortie)

        # Priorité : viré > absent > présent
        if is_vire:
            statut = "vire"
            raison = None
            if abs_row and abs_row.raison:
                raison = abs_row.raison
            elif vire_by_emp.get(eid) is not None:
                raison = "Licenciement"
            evenements: list[EvenementJour] = []
            heure_entree = None
            heure_sortie = None
            duree = None
        elif abs_row and not ents and not sorts and not pres:
            statut = "absent"
            raison = abs_row.raison
            evenements = []
            heure_entree = None
            heure_sortie = None
            duree = None
        else:
            statut = "present"
            raison = None
            evenements = []
            for e in ents:
                evenements.append(
                    EvenementJour(
                        type="entree",
                        heure=e.heure_entree.strftime("%H:%M:%S"),
                        label=f"Entrée à {e.heure_entree.strftime('%H:%M')}",
                    )
                )
            for s in sorts:
                duree_s = None
                # durée depuis dernière entrée du même jour avant cette sortie
                candidats_e = [e for e in ents if e.heure_entree <= s.heure_sortie]
                if candidats_e:
                    best = max(candidats_e, key=lambda x: x.heure_entree)
                    dt_e = datetime.combine(date_jour, best.heure_entree)
                    dt_s = datetime.combine(date_jour, s.heure_sortie)
                    duree_s = max(0, int((dt_s - dt_e).total_seconds() // 60))
                evenements.append(
                    EvenementJour(
                        type="sortie",
                        heure=s.heure_sortie.strftime("%H:%M:%S"),
                        duree_minutes=duree_s,
                        label=f"Sortie à {s.heure_sortie.strftime('%H:%M')}"
                        + (f" ({duree_s // 60}h{duree_s % 60:02d})" if duree_s is not None else ""),
                    )
                )
            heure_entree = ents[0].heure_entree.strftime("%H:%M:%S") if ents else None
            heure_sortie = sorts[-1].heure_sortie.strftime("%H:%M:%S") if sorts else None
            duree = pres.dureetravail if pres else None
            if duree is None and heure_entree and heure_sortie:
                # estimation simple
                try:
                    h_e = datetime.strptime(heure_entree, "%H:%M:%S").time()
                    h_s = datetime.strptime(heure_sortie, "%H:%M:%S").time()
                    duree = max(
                        0,
                        int(
                            (
                                datetime.combine(date_jour, h_s)
                                - datetime.combine(date_jour, h_e)
                            ).total_seconds()
                            // 60
                        ),
                    )
                except Exception:
                    pass

        result.append(
            EmployeJourOut(
                employe_id=emp.id,
                nom=emp.nom,
                prenom=emp.prenom,
                matricule=emp.matricule,
                poste=poste_map.get(emp.id_poste) if emp.id_poste else None,
                statut_jour=statut,
                heure_entree=heure_entree,
                heure_sortie=heure_sortie,
                duree_minutes=duree,
                raison=raison,
                evenements=evenements,
            )
        )

    # Tri : présents d'abord, puis absents, puis virés ; alpha dans chaque groupe
    order = {"present": 0, "absent": 1, "vire": 2}
    result.sort(key=lambda x: (order.get(x.statut_jour, 9), (x.nom or "").lower()))

    return HistoriqueJourOut(date=date_jour.isoformat(), employes=result)


# ---------------------------------------------------------------------------
# POST /employes/{id}/virer  — licenciement depuis le panneau Employés
# ---------------------------------------------------------------------------

@router.post("/employes/{employe_id}/virer", dependencies=[Depends(require_admin)])
async def virer_employe(employe_id: int, db: AsyncSession = Depends(get_db)):
    """
    Passe l'employé en Inactif, détache la carte, nettoie la biométrie,
    archive le candidat lié, et pose une marque « Viré » pour aujourd'hui
    (Absence avec raison) afin qu'il apparaisse dans Historique du jour.
    """
    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")
    if employe.status == "Inactif":
        raise HTTPException(409, "Cet employé est déjà inactif")

    aujourdhui = date.today()

    employe.status = "Inactif"
    employe.carterfid_id = None
    await nettoyer_biometrie_employe(db, employe.id)

    # Marque du jour pour l'historique journalier
    deja_abs = (
        await db.execute(
            select(Absence).where(
                Absence.idemploye == employe.id,
                Absence.dateabsence == aujourdhui,
            )
        )
    ).scalar_one_or_none()
    if deja_abs:
        deja_abs.raison = "Viré"
    else:
        db.add(
            Absence(
                idemploye=employe.id,
                dateabsence=aujourdhui,
                raison="Viré",
            )
        )

    # Candidat lié → historique
    candidat = (
        await db.execute(
            select(Candidat).where(Candidat.employe_id == employe.id)
        )
    ).scalar_one_or_none()
    if candidat and candidat.statut != "historique":
        candidat.statut = "historique"
        candidat.heure_retrait = datetime.now(timezone.utc)

    await db.commit()

    await manager.broadcast({
        "event": "vire_manuel",
        "message": f"{employe.nom} a été viré.",
        "employe_id": employe.id,
        "nom": employe.nom,
    })

    return {
        "success": True,
        "employe_id": employe.id,
        "date": aujourdhui.isoformat(),
    }
