# app/routers/simulation.py
import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.core.time_utils import aujourdhui as _aujourdhui, maintenant as _maintenant
from app.core.ws_manager import manager
from app.core.biometrie_hooks import nettoyer_biometrie_employe
from app.db.database import AsyncSessionLocal, get_db
from app.db.models import Absence, Candidat, Employe, Presence, PresenceEntree, Sortie
from app.core.simulation_events import (
    EVENTS_BY_POSTE,
    GENERAL_ACTIF,
    GENERAL_VIRE,
    Event,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


def _pick_event(poste: str, force_vire: bool = False, allow_vire: bool = False) -> Event:
    """
    Tire un événement selon les règles :
    - Jours 1-4  → uniquement actif
    - Jours 5-6  → actif ou viré (~45 % de chance)
    - Jour 7     → obligatoirement viré
    """
    pool_actif = EVENTS_BY_POSTE.get(poste, {}).get("actif", []) + GENERAL_ACTIF
    pool_vire = EVENTS_BY_POSTE.get(poste, {}).get("vire", []) + GENERAL_VIRE

    if not pool_actif and not pool_vire:
        # Sécurité : fallback minimal
        return {
            "description": "Journée ordinaire sans événement particulier.",
            "type": "present",
            "statut_final": "actif",
        }

    if force_vire:
        return random.choice(pool_vire) if pool_vire else random.choice(pool_actif)

    if allow_vire and pool_vire and random.random() < 0.45:
        return random.choice(pool_vire)

    return random.choice(pool_actif)


async def _create_day_records(
    db: AsyncSession,
    employe: Employe,
    jour: date,
    event: Event,
):
    """Crée les vraies lignes Presence / Absence / Entrée / Sortie."""
    if event["type"] == "absent":
        absence = Absence(
            idemploye=employe.id,
            dateabsence=jour,
            raison=event["description"][:250],
        )
        db.add(absence)
    else:
        # Présence avec durée aléatoire réaliste (4h à 8h30)
        duree = random.randint(240, 510)
        heure_entree = time(8, random.randint(0, 30))
        total_minutes = heure_entree.hour * 60 + heure_entree.minute + duree
        heure_sortie = time(min(total_minutes // 60, 23), total_minutes % 60)

        entree = PresenceEntree(
            id_employe=employe.id,
            date=jour,
            heure_entree=heure_entree,
            ack=True,
        )
        sortie = Sortie(
            id_employe=employe.id,
            date=jour,
            heure_sortie=heure_sortie,
        )
        presence = Presence(
            id_employe=employe.id,
            datedujour=jour,
            statut="present",
            dureetravail=duree,
        )
        db.add_all([entree, sortie, presence])


async def run_simulation(candidat_id: int):
    """
    Tâche de fond : déroule les jours 1 → 7 maximum.
    - Broadcast WebSocket à chaque jour
    - Crée de vraies lignes de présence / absence
    - Quand viré → détache la carte, passe l'employé en Inactif,
      passe le candidat en historique, marque le jour simulé pour Historique
    """
    async with AsyncSessionLocal() as db:
        candidat = await db.get(Candidat, candidat_id)
        if not candidat or not candidat.employe_id:
            return

        employe = await db.get(Employe, candidat.employe_id)
        if not employe:
            return
        
        employe.is_simulation = True
        await db.commit()
        
        poste = candidat.poste_attribue or "Vendeur"
        base_date = _aujourdhui()

        # Signal de démarrage
        await manager.broadcast({
            "event": "simulation_start",
            "candidat": {"id": candidat.id, "nom": candidat.nom},
            "poste": poste,
            "message": "Démarrage de la simulation…",
        })

        # Chargement initial (5 secondes)
        await asyncio.sleep(5)

        for day_num in range(1, 8):
            jour = base_date + timedelta(days=day_num - 1)

            force_vire = day_num == 7
            allow_vire = day_num >= 5

            event = _pick_event(poste, force_vire=force_vire, allow_vire=allow_vire)

            # Création des records réels en base
            await _create_day_records(db, employe, jour, event)
            await db.commit()

            # Broadcast du jour
            await manager.broadcast({
                "event": "simulation_day",
                "jour": day_num,
                "date": jour.isoformat(),
                "description": event["description"],
                "type": event["type"],              # "present" | "absent"
                "statut": event["statut_final"],   # "actif" | "vire"
                "poste": poste,
                "candidat": {"id": candidat.id, "nom": candidat.nom},
                "employe_id": employe.id,
            })

            # Fin de simulation si viré
            if event["statut_final"] == "vire":
                employe.status = "Inactif"
                employe.carterfid_id = None
                candidat.statut = "historique"
                # Jour *simulé* (pas now) → Historique affiche « Viré » sur la bonne date
                candidat.heure_retrait = datetime.combine(
                    jour, time(18, 0), tzinfo=timezone.utc
                )
                # Marque pour /historique/jour (priorité viré)
                if event["type"] == "absent":
                    abs_row = (
                        await db.execute(
                            select(Absence).where(
                                Absence.idemploye == employe.id,
                                Absence.dateabsence == jour,
                            )
                        )
                    ).scalar_one_or_none()
                    if abs_row:
                        abs_row.raison = f"Viré — {event['description'][:230]}"
                else:
                    db.add(
                        Absence(
                            idemploye=employe.id,
                            dateabsence=jour,
                            raison=f"Viré — {event['description'][:230]}",
                        )
                    )
                await nettoyer_biometrie_employe(db, employe.id)
                await db.commit()

                await manager.broadcast({
                    "event": "simulation_end",
                    "raison": "viré",
                    "jour": day_num,
                    "description": event["description"],
                    "candidat": {"id": candidat.id, "nom": candidat.nom},
                    "employe_id": employe.id,
                    "message": f"{candidat.nom} a été viré le jour {day_num}. La carte est libérée.",
                })
                return

            # Pause entre les jours (ajuste selon le rythme de l'expo)
            await asyncio.sleep(3.5)

        # Sécurité (ne devrait jamais arriver car jour 7 force le viré)
        jour_fin = base_date + timedelta(days=6)
        employe.status = "Inactif"
        employe.carterfid_id = None
        candidat.statut = "historique"
        candidat.heure_retrait = datetime.combine(
            jour_fin, time(18, 0), tzinfo=timezone.utc
        )
        await nettoyer_biometrie_employe(db, employe.id)
        await db.commit()

        await manager.broadcast({
            "event": "simulation_end",
            "raison": "fin_normale",
            "jour": 7,
            "candidat": {"id": candidat.id, "nom": candidat.nom},
            "employe_id": employe.id,
            "message": f"Simulation terminée pour {candidat.nom}.",
        })


@router.post("/start/{candidat_id}", dependencies=[Depends(require_admin)])
async def start_simulation(
    candidat_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Lance manuellement la simulation pour un candidat déjà accepté
    et qui possède déjà un employé lié.
    Utile pour les tests ou un relancement.
    """
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "actif":
        raise HTTPException(409, "Le candidat doit être en statut 'actif'")
    if not candidat.employe_id:
        raise HTTPException(400, "Aucun employé lié à ce candidat")

    background_tasks.add_task(run_simulation, candidat_id)

    return {
        "success": True,
        "message": "Simulation démarrée",
        "candidat_id": candidat_id,
    }
