"""
Identique à l'original, SAUF :
  - les imports de app.core.biometrie -> app.core.face_client (appel HTTP
    vers ton PC au lieu d'un calcul local)
  - ajout de la gestion de FaceServerIndisponible -> 503, pour ne pas
    planter bêtement si ton PC/tunnel est down pendant l'expo.
  - /enroll/{employe_id} n'utilise plus require_admin (JWT qui expire au
    bout d'1h) mais un secret statique X-Ecran-Secret, comme l'écran
    kiosque (voir app/routers/candidats.py::tache_active_ecran). Doit
    correspondre à settings.ECRAN_SHARED_SECRET. Conservé pour un usage
    admin/dépannage, mais N'EST PLUS appelé par sys_ecran (voir plus bas).
  - NOUVEAU : /enroll-public, appelé directement depuis le téléphone du
    candidat (caméra frontale du téléphone). L'enrôlement biométrique ne
    se fait donc plus sur l'écran kiosque. Comme /candidats/mon-statut,
    la "credential" est simplement le candidat_id reçu à l'inscription
    (aucun secret statique à embarquer dans une app publique) ; on
    rate-limite la route pour limiter les abus.
  - NOUVEAU (2 capteurs physiques) : /verify a été scindé en
    /verify-entree et /verify-sortie. Chaque capteur (carte + caméra)
    appelle SON endpoint dédié. Chaque endpoint vérifie l'état actuel de
    la carte (carte.isentree) et REFUSE (409) si l'état ne correspond
    pas au sens attendu, au lieu de basculer aveuglément comme avant.
    Ça évite qu'une carte déjà "dedans" soit re-comptée comme une entrée
    (ou l'inverse) si quelqu'un se trompe de capteur ou rebadge deux fois
    sur le même. L'ancien /verify est conservé tel quel pour compat
    descendante (dépannage / test à un seul capteur), mais n'est plus le
    chemin utilisé par les 2 capteurs physiques.
  - NOUVEAU (fuseau horaire) : date.today() et datetime.now() ont été
    remplacés par app.core.time_utils.aujourdhui()/maintenant(), pour
    utiliser l'heure de Madagascar (UTC+3) au lieu de l'heure du serveur
    (UTC). Sinon toute entrée/sortie entre ~21h et minuit était enregistrée
    avec la mauvaise date (celle du serveur, en retard de 3h).
Tout le reste (DB, websockets, logique carte+visage) est inchangé.

NOTE : l'attribution du poste n'est plus tirée au sort ici. L'enrôlement du
visage se contente d'enregistrer l'encoding ; c'est le candidat qui choisit
ensuite lui-même son poste depuis son téléphone, voir
app/routers/candidats.py::choisir_poste.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import aujourdhui as _aujourdhui, maintenant as _maintenant
from app.core.face_client import (
    SEUIL_DEFAUT,
    AucunVisageDetecte,
    FaceServerIndisponible,
    PlusieursVisagesDetectes,
    image_bytes_vers_encoding,
    visage_correspond,
)
from app.core.biometrie_hooks import nettoyer_biometrie_employe
from app.core.porte_pending import mark_authorized
from app.core.security import require_admin
from app.core.ws_manager import manager
from app.db.database import get_db
from app.db.models import (
    Candidat,
    Carterfid,
    Employe,
    FaceEncoding,
    Presence,
    PresenceEntree,
    Sortie,
)

router = APIRouter(prefix="/api/biometrie", tags=["biometrie"])
limiter = Limiter(key_func=get_remote_address)


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




def _verifier_secret_ecran(x_ecran_secret: str | None):
    if x_ecran_secret != settings.ECRAN_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Secret écran invalide")


async def _enrolir_employe(employe: Employe, contenu_photo: bytes, db: AsyncSession) -> dict:
    """
    Logique métier partagée par /enroll/{employe_id} (dépannage admin/écran)
    et /enroll-public (téléphone du candidat) : encode le visage et le
    stocke. N'attribue plus aucun poste (voir app/routers/candidats.py::
    choisir_poste pour l'étape suivante, choisie par le candidat lui-même).
    Ne fait AUCUNE vérification d'autorisation : c'est aux endpoints
    appelants de s'en charger avant d'appeler cette fonction.
    """
    if employe.status != "Actif":
        raise HTTPException(409, "Impossible d'enregistrer un visage pour un employé inactif")

    try:
        encoding = await image_bytes_vers_encoding(contenu_photo)
    except AucunVisageDetecte:
        raise HTTPException(422, "Aucun visage détecté : replace-toi dans le cadre")
    except PlusieursVisagesDetectes:
        raise HTTPException(422, "Plusieurs visages détectés : une seule personne à la fois dans le cadre")
    except FaceServerIndisponible:
        raise HTTPException(503, "Service de reconnaissance faciale indisponible (PC hors ligne ?)")

    existant = (
        await db.execute(select(FaceEncoding).where(FaceEncoding.employe_id == employe.id))
    ).scalar_one_or_none()

    if existant:
        existant.encoding = encoding
    else:
        db.add(FaceEncoding(employe_id=employe.id, encoding=encoding))

    await db.commit()
    await db.refresh(employe)

    candidat = (
        await db.execute(select(Candidat).where(Candidat.employe_id == employe.id))
    ).scalar_one_or_none()

    await manager.broadcast({
        "event": "visage_enrole",
        "employe_id": employe.id,
        "candidat": {"id": candidat.id, "nom": candidat.nom} if candidat else None,
        "message": (
            f"{candidat.nom if candidat else 'Le candidat'} a enrôlé son visage. "
            f"Il ne lui reste plus qu'à choisir son poste."
        ),
    })

    return {
        "success": True,
        "message": "Visage enregistré avec succès",
        "employe_id": employe.id,
    }


@router.post("/enroll/{employe_id}")
async def enroll_visage(
    employe_id: int,
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    x_ecran_secret: str | None = Header(default=None),
):
    """
    Conservé comme filet de secours (dépannage régie / admin), mais n'est
    plus utilisé par le parcours normal : l'enrôlement se fait désormais
    depuis le téléphone du candidat via /enroll-public.
    """
    _verifier_secret_ecran(x_ecran_secret)

    employe = await db.get(Employe, employe_id)
    if not employe:
        raise HTTPException(404, "Employé non trouvé")

    contenu = await photo.read()
    return await _enrolir_employe(employe, contenu, db)


@router.post("/enroll-public")
@limiter.limit("1/3seconds")
async def enroll_visage_public(
    request: Request,
    candidat_id: int = Form(...),
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Enrôlement biométrique depuis le téléphone du candidat (caméra
    frontale), déclenché par le bouton "Enrôler votre visage" dans
    systeme_presence_user. Comme /candidats/mon-statut, l'identifiant du
    candidat (reçu à l'inscription, stocké côté client) suffit : c'est
    cohérent avec le niveau de sécurité du reste de l'app publique, et ça
    évite d'embarquer un secret statique dans un front accessible à tous
    les visiteurs (contrairement à l'écran kiosque, physiquement contrôlé).
    """
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "actif":
        raise HTTPException(409, "Ce candidat n'est pas (ou plus) actif")
    if not candidat.employe_id:
        raise HTTPException(409, "Aucun employé associé à ce candidat")

    employe = await db.get(Employe, candidat.employe_id)
    if not employe:
        raise HTTPException(404, "Employé introuvable pour ce candidat")

    contenu = await photo.read()
    resultat = await _enrolir_employe(employe, contenu, db)
    resultat["candidat_id"] = candidat.id
    return resultat

@router.post("/demander-enrolement-ecran")
@limiter.limit("1/5seconds")
async def demander_enrolement_ecran(
    request: Request,
    candidat_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Le téléphone du candidat signale que sa caméra est inutilisable
    (permission refusée, matériel défaillant, etc.). L'écran kiosque
    reçoit l'événement `enrolement_ecran_demande` et bascule en mode
    enrôlement ciblé pour ce candidat uniquement.
    """
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "actif":
        raise HTTPException(409, "Ce candidat n'est pas (ou plus) actif")
    if not candidat.employe_id:
        raise HTTPException(409, "Aucun employé associé à ce candidat")

    employe = await db.get(Employe, candidat.employe_id)
    if not employe:
        raise HTTPException(404, "Employé introuvable pour ce candidat")
    if employe.status != "Actif":
        raise HTTPException(409, "Employé inactif")

    # Déjà enrôlé ? pas la peine de relancer l'écran
    existant = (
        await db.execute(select(FaceEncoding).where(FaceEncoding.employe_id == employe.id))
    ).scalar_one_or_none()
    if existant:
        raise HTTPException(409, "Le visage est déjà enregistré")

    await manager.broadcast({
        "event": "enrolement_ecran_demande",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "employe_id": employe.id,
        "message": f"{candidat.nom} demande à enrôler son visage sur l'écran.",
    })

    return {
        "success": True,
        "message": "L'écran kiosque a été notifié. Placez-vous devant lui.",
        "employe_id": employe.id,
        "candidat_id": candidat.id,
        "nom": candidat.nom,
    }


async def _verifier_carte_et_visage(
    uidcarte: str,
    photo: UploadFile,
    seuil: float,
    db: AsyncSession,
):
    """
    Étapes communes aux 2 capteurs (entrée / sortie) : retrouver la carte,
    l'employé, vérifier le statut, et comparer le visage. Ne touche PAS à
    carte.isentree ni à la création des lignes PresenceEntree/Sortie :
    ça reste spécifique à chaque sens, géré par l'appelant.

    Retourne soit un dict {"result": "DENIED", ...} à renvoyer tel quel,
    soit un tuple (carte, employe, dist) si tout est bon.
    """
    uidcarte = _normaliser_uid(uidcarte)
    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == uidcarte))
    ).scalar_one_or_none()
    if not carte:
        return {"result": "DENIED", "reason": "carte_inconnue"}

    employe = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if not employe:
        return {"result": "DENIED", "reason": "carte_non_assignee"}

    if employe.status != "Actif":
        await manager.broadcast({
            "event": "acces_refuse",
            "reason": "employe_inactif",
            "employe_id": employe.id,
            "message": "Accès refusé : employé inactif.",
        })
        return {"result": "DENIED", "reason": "employe_inactif", "employe_id": employe.id}

    face_row = (
        await db.execute(select(FaceEncoding).where(FaceEncoding.employe_id == employe.id))
    ).scalar_one_or_none()
    if not face_row:
        return {"result": "DENIED", "reason": "aucun_visage_enregistre", "employe_id": employe.id}

    contenu = await photo.read()
    try:
        encoding_actuel = await image_bytes_vers_encoding(contenu)
    except AucunVisageDetecte:
        return {"result": "DENIED", "reason": "aucun_visage_detecte", "employe_id": employe.id}
    except PlusieursVisagesDetectes:
        return {"result": "DENIED", "reason": "plusieurs_visages_detectes", "employe_id": employe.id}
    except FaceServerIndisponible:
        raise HTTPException(503, "Service de reconnaissance faciale indisponible (PC hors ligne ?)")

    correspond, dist = await visage_correspond(face_row.encoding, encoding_actuel, seuil=seuil)

    if not correspond:
        await manager.broadcast({
            "event": "acces_refuse",
            "reason": "visage_non_reconnu",
            "employe_id": employe.id,
            "distance": round(dist, 4),
            "message": "Accès refusé : visage non reconnu.",
        })
        return {
            "result": "DENIED",
            "reason": "visage_non_reconnu",
            "employe_id": employe.id,
            "distance": round(dist, 4),
        }

    return carte, employe, dist


@router.post("/verify-entree")
async def verifier_visage_entree(
    uidcarte: str = Form(...),
    photo: UploadFile = File(...),
    seuil: float = Form(SEUIL_DEFAUT),
    db: AsyncSession = Depends(get_db),
):
    """
    Capteur physique d'ENTRÉE (carte + caméra). Carte + visage vérifiés
    comme avant, MAIS : si la carte est déjà marquée comme "dedans"
    (carte.isentree == True), on REFUSE (409) au lieu de basculer en
    sortie. La personne s'est trompée de capteur, ou rebadge deux fois
    de suite : dans les deux cas ce n'est pas une entrée valide.
    """
    resultat = await _verifier_carte_et_visage(uidcarte, photo, seuil, db)
    if isinstance(resultat, dict):
        return resultat
    carte, employe, dist = resultat

    if carte.isentree:
        return {
            "result": "DENIED",
            "reason": "deja_entre",
            "employe_id": employe.id,
            "message": f"{employe.nom} est déjà marqué comme entré. Utilisez le capteur de sortie.",
        }

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
        presence = Presence(
            id_employe=employe.id,
            datedujour=aujourdhui,
            statut="present",
        )
        db.add(presence)
    db.add(entree)

    await db.commit()

    message = f"{employe.nom} est entré dans l'entreprise."
    await manager.broadcast({
        "event": "entree_entreprise",
        "message": message,
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "biometrie",
        "heure": heure_str,
        "action": "entree",
    })

    # Signale à l'ESP32 (via /api/porte/peut-ouvrir) que le visage est validé
    mark_authorized(_normaliser_uid(uidcarte))

    return {
        "result": "AUTHORIZED",
        "action": "entree",
        "employe_id": employe.id,
        "nom": employe.nom,
        "distance": round(dist, 4),
        "heure": heure_str,
        "is_present": True,
    }


@router.post("/verify-sortie")
async def verifier_visage_sortie(
    uidcarte: str = Form(...),
    photo: UploadFile = File(...),
    seuil: float = Form(SEUIL_DEFAUT),
    db: AsyncSession = Depends(get_db),
):
    """
    Capteur physique de SORTIE (carte + caméra). Symétrique à
    /verify-entree : si la carte n'est PAS marquée comme "dedans"
    (carte.isentree == False), on REFUSE (409) au lieu d'enregistrer
    une sortie fantôme.
    """
    resultat = await _verifier_carte_et_visage(uidcarte, photo, seuil, db)
    if isinstance(resultat, dict):
        return resultat
    carte, employe, dist = resultat

    if not carte.isentree:
        return {
            "result": "DENIED",
            "reason": "pas_encore_entre",
            "employe_id": employe.id,
            "message": f"{employe.nom} n'est pas marqué comme entré. Utilisez le capteur d'entrée.",
        }

    aujourdhui = _aujourdhui()
    heure_actuelle = _maintenant().time()
    heure_str = heure_actuelle.strftime("%H:%M:%S")

    heure_entree_str = None
    duree_minutes = None

    sortie = Sortie(
        id_employe=employe.id,
        date=aujourdhui,
        heure_sortie=heure_actuelle,
    )
    carte.isentree = False
    db.add(sortie)

    # Récupère la dernière entrée du jour sans sortie appariée (la plus récente)
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

    message = f"{employe.nom} est sorti de l'entreprise."
    payload_ws = {
        "event": "sortie_entreprise",
        "message": message,
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "biometrie",
        "heure": heure_str,
        "action": "sortie",
    }
    if heure_entree_str:
        payload_ws["heure_entree"] = heure_entree_str
    if duree_minutes is not None:
        payload_ws["duree_minutes"] = duree_minutes
    await manager.broadcast(payload_ws)

    response = {
        "result": "AUTHORIZED",
        "action": "sortie",
        "employe_id": employe.id,
        "nom": employe.nom,
        "distance": round(dist, 4),
        "heure": heure_str,
        "is_present": False,
    }
    if heure_entree_str:
        response["heure_entree"] = heure_entree_str
    if duree_minutes is not None:
        response["duree_minutes"] = duree_minutes

    # Signale à l'ESP32 (via /api/porte/peut-ouvrir) que le visage est validé
    mark_authorized(_normaliser_uid(uidcarte))
    return response


@router.post("/verify")
async def verifier_visage(
    uidcarte: str = Form(...),
    photo: UploadFile = File(...),
    seuil: float = Form(SEUIL_DEFAUT),
    db: AsyncSession = Depends(get_db),
):
    """
    ANCIEN endpoint à bascule automatique (un seul capteur physique).
    Conservé pour compat descendante / dépannage, mais les 2 capteurs
    physiques (entrée + sortie) doivent utiliser /verify-entree et
    /verify-sortie ci-dessus, qui rejettent l'état incohérent au lieu
    de basculer aveuglément.
    """
    resultat = await _verifier_carte_et_visage(uidcarte, photo, seuil, db)
    if isinstance(resultat, dict):
        return resultat
    carte, employe, dist = resultat

    aujourdhui = _aujourdhui()
    heure_actuelle = _maintenant().time()
    heure_str = heure_actuelle.strftime("%H:%M:%S")

    heure_entree_str = None
    duree_minutes = None

    if not carte.isentree:
        action = "entree"
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
            presence = Presence(
                id_employe=employe.id,
                datedujour=aujourdhui,
                statut="present",
            )
            db.add(presence)
        db.add(entree)
        message = f"{employe.nom} est entré dans l'entreprise."
    else:
        action = "sortie"
        sortie = Sortie(
            id_employe=employe.id,
            date=aujourdhui,
            heure_sortie=heure_actuelle,
        )
        carte.isentree = False
        db.add(sortie)

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

        message = f"{employe.nom} est sorti de l'entreprise."

    await db.commit()

    payload_ws = {
        "event": f"{action}_entreprise",
        "message": message,
        "employe_id": employe.id,
        "nom": employe.nom,
        "via": "biometrie",
        "heure": heure_str,
        "action": action,
    }
    if heure_entree_str:
        payload_ws["heure_entree"] = heure_entree_str
    if duree_minutes is not None:
        payload_ws["duree_minutes"] = duree_minutes

    await manager.broadcast(payload_ws)

    response = {
        "result": "AUTHORIZED",
        "action": action,
        "employe_id": employe.id,
        "nom": employe.nom,
        "distance": round(dist, 4),
        "heure": heure_str,
        "is_present": carte.isentree,
    }
    if heure_entree_str:
        response["heure_entree"] = heure_entree_str
    if duree_minutes is not None:
        response["duree_minutes"] = duree_minutes

    # Signale à l'ESP32 (via /api/porte/peut-ouvrir) que le visage est validé
    mark_authorized(_normaliser_uid(uidcarte))
    return response


@router.delete("/{employe_id}", dependencies=[Depends(require_admin)])
async def supprimer_visage(employe_id: int, db: AsyncSession = Depends(get_db)):
    supprime = await nettoyer_biometrie_employe(db, employe_id)
    await db.commit()
    if not supprime:
        raise HTTPException(404, "Aucun encoding enregistré pour cet employé")
    return {"success": True, "message": "Encoding facial supprimé"}