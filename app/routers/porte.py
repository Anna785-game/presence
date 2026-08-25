"""
Endpoint dédié aux boîtiers physiques ESP32 (2 lecteurs RFID + servos +
LCD + LEDs), PAS au kiosque sys_ecran.

RECONNAISSANCE FACIALE ACTIVÉE :
/verifier-carte valide la carte, crée un pending (create_pending) et
broadcast porte_carte_ok pour le kiosque. L'ouverture n'est autorisée
qu'après validation du visage via /api/biometrie/verify (mark_authorized).
L'ESP32 continue de poller /peut-ouvrir comme avant.

Rôle (inchangé par ailleurs) :
  - Vérifier que la carte est connue et assignée à un employé actif
    → ouverture porte + broadcast porte_carte_ok (écran facial).
  - Si la carte est inconnue → l'enregistrer automatiquement dans
    carterfid (libre, non assignée) + broadcast carte_enregistree
    pour que CartesPanel / le fil live se mettent à jour. La porte
    reste fermée (pas d'employé lié).
  - Si la carte est connue mais non assignée → refus + broadcast
    carte_libre_scannee (déjà en base, encore libre).

Auth : header X-Porte-Secret (= settings.PORTE_SHARED_SECRET).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.porte_pending import (
    clear_old,
    clear_pending,
    consume_if_authorized,
    create_pending,
    get_pending,
)
from app.core.time_utils import aujourdhui as _aujourdhui, maintenant as _maintenant
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import Carterfid, Employe, Presence, PresenceEntree, Sortie

router = APIRouter(prefix="/api/porte", tags=["porte"])


def _verifier_secret_porte(x_porte_secret: str | None):
    if x_porte_secret != settings.PORTE_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Secret porte invalide")


def _normaliser_uid(uid: str) -> str:
    """UID ESP32 : majuscules, sans espaces / ':' / '-'."""
    return (
        (uid or "")
        .strip()
        .upper()
        .replace(" ", "")
        .replace(":", "")
        .replace("-", "")
    )


class VerifCarteRequest(BaseModel):
    uidcarte: str
    # "entree" | "sortie" : détermine le sens enregistré
    sens: str | None = None


async def _enregistrer_entree(db: AsyncSession, employe: Employe, carte: Carterfid) -> dict:
    """Reprend la logique de app/routers/biometrie.py::verifier_visage_entree,
    sans la vérification de visage (désactivée temporairement)."""
    aujourdhui = _aujourdhui()
    heure_actuelle = _maintenant().time()
    heure_str = heure_actuelle.strftime("%H:%M:%S")

    entree = PresenceEntree(
        id_employe=employe.id,
        date=aujourdhui,
        heure_entree=heure_actuelle,
        ack=True,
    )
    carte.isentree = True

    presence = (
        await db.execute(
            select(Presence).where(
                Presence.id_employe == employe.id,
                Presence.datedujour == aujourdhui,
            )
        )
    ).scalar_one_or_none()
    if not presence:
        presence = Presence(id_employe=employe.id, datedujour=aujourdhui, statut="present")
        db.add(presence)
    db.add(entree)
    await db.commit()

    await manager.broadcast({
        "event": "entree_entreprise",
        "message": f"{employe.nom} est entré dans l'entreprise.",
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "carte",
        "heure": heure_str,
        "action": "entree",
    })
    return {"heure": heure_str}


async def _enregistrer_sortie(db: AsyncSession, employe: Employe, carte: Carterfid) -> dict:
    """Reprend la logique de app/routers/biometrie.py::verifier_visage_sortie,
    sans la vérification de visage (désactivée temporairement)."""
    aujourdhui = _aujourdhui()
    heure_actuelle = _maintenant().time()
    heure_str = heure_actuelle.strftime("%H:%M:%S")

    sortie = Sortie(id_employe=employe.id, date=aujourdhui, heure_sortie=heure_actuelle)
    carte.isentree = False
    db.add(sortie)

    heure_entree_str = None
    duree_minutes = None
    derniere_entree = (
        await db.execute(
            select(PresenceEntree)
            .where(PresenceEntree.id_employe == employe.id, PresenceEntree.date == aujourdhui)
            .order_by(PresenceEntree.heure_entree.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

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

    payload_ws = {
        "event": "sortie_entreprise",
        "message": f"{employe.nom} est sorti de l'entreprise.",
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "carte",
        "heure": heure_str,
        "action": "sortie",
    }
    if heure_entree_str:
        payload_ws["heure_entree"] = heure_entree_str
    if duree_minutes is not None:
        payload_ws["duree_minutes"] = duree_minutes
    await manager.broadcast(payload_ws)
    return {"heure": heure_str}


@router.post("/verifier-carte")
async def verifier_carte(
    payload: VerifCarteRequest,
    db: AsyncSession = Depends(get_db),
    x_porte_secret: str | None = Header(default=None),
):
    _verifier_secret_porte(x_porte_secret)

    uid = _normaliser_uid(payload.uidcarte)
    if not uid:
        raise HTTPException(400, "uidcarte manquant")

    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == uid))
    ).scalar_one_or_none()

    # --- Carte inconnue → auto-enregistrement (libre) ---
    if not carte:
        carte = Carterfid(uidcarte=uid, couleur=None, isentree=False)
        db.add(carte)
        await db.commit()
        await db.refresh(carte)

        await manager.broadcast(
            {
                "event": "carte_enregistree",
                "carte_id": carte.id,
                "carte_uid": carte.uidcarte,
                "message": f"Nouvelle carte scannée et enregistrée : {carte.uidcarte} (libre).",
            }
        )

        return {
            "autorise": False,
            "raison": "carte_nouvelle_enregistree",
            "carte_id": carte.id,
            "carte_uid": carte.uidcarte,
            "message": "Carte enregistrée. Attribuez-la à un employé depuis la régie.",
        }

    employe = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()

    # --- Connue mais personne ne l'a ---
    if not employe:
        await manager.broadcast(
            {
                "event": "carte_libre_scannee",
                "carte_id": carte.id,
                "carte_uid": carte.uidcarte,
                "message": f"Carte libre scannée : {carte.uidcarte} (déjà en base, non attribuée).",
            }
        )
        return {
            "autorise": False,
            "raison": "carte_non_assignee",
            "carte_id": carte.id,
            "carte_uid": carte.uidcarte,
        }

    if employe.status != "Actif":
        return {
            "autorise": False,
            "raison": "employe_inactif",
            "employe_id": employe.id,
        }

    sens = payload.sens if payload.sens in ("entree", "sortie") else "entree"

    # --- RECONNAISSANCE FACIALE ACTIVÉE ---------------------------------
    # Cohérence du sens uniquement. Pas d'enregistrement présence ni
    # mark_authorized ici : c'est /api/biometrie/verify après le visage.
    if sens == "entree" and carte.isentree:
        return {
            "autorise": False,
            "raison": "deja_entre",
            "employe_id": employe.id,
            "message": f"{employe.nom} est déjà marqué comme entré. Utilisez le lecteur de sortie.",
        }
    if sens == "sortie" and not carte.isentree:
        return {
            "autorise": False,
            "raison": "pas_encore_entre",
            "employe_id": employe.id,
            "message": f"{employe.nom} n'est pas marqué comme entré. Utilisez le lecteur d'entrée.",
        }

    nom_affiche = (employe.nom or "").strip() or "Employé"
    sens_label = "entrée" if sens == "entree" else "sortie"

    # Pending en attente de validation faciale (ESP32 pollera /peut-ouvrir)
    create_pending(
        uid=carte.uidcarte,
        sens=sens,
        employe_id=employe.id,
        nom=employe.nom or "",
    )
    # PAS de mark_authorized ici — le visage le fera

    await manager.broadcast(
        {
            "event": "porte_carte_ok",
            "uidcarte": carte.uidcarte,
            "employe_id": employe.id,
            "nom": employe.nom,
            "prenom": employe.prenom,
            "sens": sens,
            "message": f"{nom_affiche}, placez-vous devant l'écran.",
        }
    )

    return {
        "autorise": True,
        "employe_id": employe.id,
        "nom": employe.nom,
        "sens": sens,
        "message": f"Carte valide. En attente du visage pour la {sens_label}.",
        "attente_visage": True,
    }


@router.get("/peut-ouvrir")
async def peut_ouvrir(
    uidcarte: str,
    x_porte_secret: str | None = Header(default=None),
):
    """
    Polling ESP32 : après un scan carte OK, l'ESP32 interroge cet endpoint
    jusqu'à ce que le visage soit validé (mark_authorized depuis
    /api/biometrie/verify) ou timeout.
    """
    _verifier_secret_porte(x_porte_secret)
    clear_old(90)

    uid = _normaliser_uid(uidcarte)
    p = get_pending(uid)

    if not p:
        return {"peut_ouvrir": False, "raison": "aucune_demande"}

    if not p.authorized:
        return {
            "peut_ouvrir": False,
            "raison": "en_attente_visage",
            "sens": p.sens,
            "nom": p.nom,
        }

    # One-shot : on consomme pour éviter une double ouverture
    consumed = consume_if_authorized(uid)
    if not consumed:
        return {"peut_ouvrir": False, "raison": "deja_consomme"}

    return {
        "peut_ouvrir": True,
        "sens": consumed.sens,
        "employe_id": consumed.employe_id,
        "nom": consumed.nom,
    }


@router.post("/annuler")
async def annuler_ouverture(
    payload: VerifCarteRequest,
    x_porte_secret: str | None = Header(default=None),
):
    """Optionnel : l'ESP32 peut annuler une demande si timeout visage."""
    _verifier_secret_porte(x_porte_secret)
    uid = _normaliser_uid(payload.uidcarte)
    clear_pending(uid)
    return {"ok": True}