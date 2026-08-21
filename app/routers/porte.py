"""
Endpoint dédié aux boîtiers physiques ESP32 (2 lecteurs RFID + servos +
LCD + LEDs), PAS au kiosque sys_ecran.

Rôle :
  - Vérifier que la carte est connue et assignée à un employé actif
    → ouverture porte + broadcast porte_carte_ok (écran facial).
  - Si la carte est inconnue → l'enregistrer automatiquement dans
    carterfid (libre, non assignée) + broadcast carte_enregistree
    pour que CartesPanel / le fil live se mettent à jour. La porte
    reste fermée (pas d'employé lié).
  - Si la carte est connue mais non assignée → refus + broadcast
    carte_libre_scannee (déjà en base, encore libre).

Ne touche PAS à carte.isentree ni aux tables de présence : c'est
sys_ecran + /api/biometrie/verify qui enregistrent l'entrée/sortie.

Auth : header X-Porte-Secret (= settings.PORTE_SHARED_SECRET).
"""
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
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import Carterfid, Employe

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
    # "entree" | "sortie" : informatif (logs + message WS)
    sens: str | None = None


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

    # --- OK : employé actif ---
    sens_label = (
        "entrée"
        if payload.sens == "entree"
        else "sortie"
        if payload.sens == "sortie"
        else "accès"
    )
    nom_affiche = (employe.nom or "").strip() or "Employé"

    await manager.broadcast(
        {
            "event": "porte_carte_ok",
            "uidcarte": carte.uidcarte,
            "employe_id": employe.id,
            "nom": employe.nom,
            "prenom": employe.prenom,
            "sens": payload.sens,
            "message": (
                f"{nom_affiche}, placez-vous devant l'écran pour la "
                f"vérification faciale ({sens_label})."
            ),
        }
    )

    # Demande d'ouverture en attente de validation faciale (polling ESP32)
    create_pending(
        uid=carte.uidcarte,
        sens=payload.sens or "entree",
        employe_id=employe.id,
        nom=employe.nom or "",
    )

    return {
        "autorise": True,
        "employe_id": employe.id,
        "nom": employe.nom,
        "message": "Carte valide. Rendez-vous devant l'écran pour la vérification faciale.",
    }


@router.get("/peut-ouvrir")
async def peut_ouvrir(
    uidcarte: str,
    x_porte_secret: str | None = Header(default=None),
):
    """
    Polling ESP32 : après un scan carte OK, l'ESP32 interroge cet endpoint
    jusqu'à ce que le visage soit validé (ou timeout côté ESP).
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

