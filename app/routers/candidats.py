# app/routers/candidats.py
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import delete, select, update
from app.core.config import settings
from app.core.time_utils import aujourdhui as _aujourdhui, maintenant as _maintenant
from app.core.security import require_admin
from app.db.database import get_db
from app.db.models import Candidat, Carterfid, Employe, FaceEncoding, Poste
from app.schemas.schemas import CandidatInscription, CandidatOut
from app.core.biometrie_hooks import nettoyer_biometrie_employe
from datetime import date, datetime, timezone
from sqlalchemy import func
from app.core.ws_manager import manager

router = APIRouter(prefix="/candidats", tags=["candidats"])
limiter = Limiter(key_func=get_remote_address)


# --- Reconnaissance faciale désactivée temporairement --------------------
# Le matériel / la reconnaissance faciale n'est pas encore prête. En
# attendant, on utilise 2 cartes RFID PERMANENTES (fabriquées une bonne
# fois pour toutes) qui sont attribuées automatiquement dès que le
# candidat choisit son poste, sans passer par l'enrôlement du visage ni
# par la remise physique manuelle (écran / admin).
#
# Pour réactiver la reconnaissance faciale plus tard : remettre la
# vérification `if not face_row: raise HTTPException(...)` dans
# `choisir_poste` ci-dessous, et arrêter d'appeler
# `_attribuer_carte_automatique` (revenir à l'attribution manuelle via
# app/routers/cartes.py ou l'écran, comme avant).
CARTES_FIXES_UID = ["F38E296F", "8BE8286F", "AA837C05", "F3780307"]


async def _assurer_cartes_fixes(db: AsyncSession) -> list[Carterfid]:
    """
    Garantit que les 2 cartes RFID permanentes existent en base (créées
    au tout premier appel si besoin, puis simplement relues ensuite).
    """
    cartes = []
    for uid in CARTES_FIXES_UID:
        carte = (
            await db.execute(select(Carterfid).where(Carterfid.uidcarte == uid))
        ).scalar_one_or_none()
        if not carte:
            carte = Carterfid(uidcarte=uid, isentree=False)
            db.add(carte)
            await db.flush()
        cartes.append(carte)
    return cartes


async def _attribuer_carte_automatique(db: AsyncSession, employe: Employe) -> Carterfid:
    """
    Attribue à `employe` la première des 2 cartes fixes qui n'est pas déjà
    liée à un autre employé. Lève 409 si les 2 sont déjà prises (aucune
    n'a encore été libérée par un licenciement, voir virer_manuellement
    ci-dessous qui remet employe.carterfid_id à None).
    Ne fait PAS le commit : à faire dans le même commit que le choix du
    poste, pour rester atomique.
    """
    cartes = await _assurer_cartes_fixes(db)
    for carte in cartes:
        deja_prise = (
            await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
        ).scalar_one_or_none()
        if not deja_prise:
            employe.carterfid_id = carte.id
            return carte

    raise HTTPException(
        409,
        f"Les {len(CARTES_FIXES_UID)} cartes disponibles sont déjà attribuées à des employés actifs. "
        "Il faut en libérer une (licenciement) avant de pouvoir en attribuer une nouvelle.",
    )


async def _avec_visage_enrole(db: AsyncSession, candidat: Candidat) -> Candidat:
    """
    Attache 2 attributs non mappés en base au candidat, lus ensuite par
    CandidatOut :
      - `visage_enrole` : conservé pour compat (toujours False tant que la
        reconnaissance faciale est désactivée, voir plus haut), au cas où
        un vieux visage aurait quand même été enrôlé via /enroll (admin).
      - `carte_uid` : l'UID de la carte RFID attribuée automatiquement,
        affiché au candidat une fois son poste choisi (voir Parcours.jsx
        côté systeme_presence_user).
    """
    visage = False
    carte_uid = None
    if candidat.employe_id:
        existant = (
            await db.execute(
                select(FaceEncoding.id).where(FaceEncoding.employe_id == candidat.employe_id)
            )
        ).scalar_one_or_none()
        visage = existant is not None

        employe = await db.get(Employe, candidat.employe_id)
        if employe and employe.carterfid_id:
            carte = await db.get(Carterfid, employe.carterfid_id)
            carte_uid = carte.uidcarte if carte else None

    candidat.visage_enrole = visage
    candidat.carte_uid = carte_uid
    return candidat

# --- Public : inscription visiteur ---

@router.post("/inscription", response_model=CandidatOut, status_code=201)
@limiter.limit("1/20seconds")
async def inscription(
    request: Request,
    payload: CandidatInscription,
    db: AsyncSession = Depends(get_db),
):
    nom = payload.nom.strip()
    if not nom or len(nom) > 50:
        raise HTTPException(400, "Nom invalide")

    # Normalisation simple (insensible à la casse + espaces)
    nom_norm = " ".join(nom.lower().split())

    # Vérifier s’il existe déjà un candidat "en cours" avec ce nom
    existant = (
        await db.execute(
            select(Candidat).where(
                func.lower(func.trim(Candidat.nom)) == nom_norm,
                Candidat.statut.in_(["attente", "actif"]),
            )
        )
    ).scalar_one_or_none()

    if existant:
        # On renvoie l’existant au lieu d’en créer un nouveau
        # (le front peut afficher "Tu es déjà inscrit, voici ton statut")
        return existant

    candidat = Candidat(
        nom=nom,
        statut="attente",
        ip_inscription=get_remote_address(request),
    )
    db.add(candidat)
    await db.commit()
    await db.refresh(candidat)

    await manager.broadcast({
        "event": "inscription",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
    })
    return candidat


@router.get("/mon-statut", response_model=CandidatOut)
async def mon_statut(candidat_id: int, db: AsyncSession = Depends(get_db)):
    """Le visiteur consulte son propre statut avec l'id reçu à l'inscription."""
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    return await _avec_visage_enrole(db, candidat)


# --- Public : choix du poste par le candidat lui-même ---

@router.get("/postes-disponibles")
async def postes_disponibles(db: AsyncSession = Depends(get_db)):
    """
    Liste publique (pas d'auth admin) des postes que le candidat peut
    choisir depuis son téléphone. Remplace l'ancienne roulette : ce n'est
    plus un tirage au sort, mais un choix explicite parmi les postes
    configurés côté admin (voir app/routers/postes.py, panneau "Postes"
    du back-office).
    """
    postes = (await db.execute(select(Poste).order_by(Poste.id))).scalars().all()
    return [{"id": p.id, "type_poste": p.type_poste} for p in postes]


@router.post("/{candidat_id}/choisir-poste", response_model=CandidatOut)
async def choisir_poste(candidat_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    """
    Le candidat choisit lui-même son poste depuis son téléphone.

    RECONNAISSANCE FACIALE DÉSACTIVÉE TEMPORAIREMENT : contrairement à la
    version précédente, on n'exige plus `visage_enrole` avant de choisir
    un poste (plus de redirection vers /enrolement côté front). Dès le
    poste choisi, une carte RFID est attribuée automatiquement parmi les
    2 cartes fixes (voir _attribuer_carte_automatique ci-dessus) — il n'y
    a donc plus besoin que l'admin ou l'écran remette une carte à la main.
    """
    poste_id = (payload or {}).get("poste_id")
    if not poste_id:
        raise HTTPException(400, "poste_id manquant")

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

    if employe.id_poste is not None:
        raise HTTPException(409, "Un poste a déjà été choisi pour cet employé")

    poste = await db.get(Poste, poste_id)
    if not poste:
        raise HTTPException(404, "Poste non trouvé")

    employe.id_poste = poste.id
    candidat.poste_attribue = poste.type_poste

    # Attribution automatique d'une des 2 cartes fixes (lève 409 si les 2
    # sont déjà prises). Fait AVANT le commit pour que tout soit atomique :
    # si l'attribution échoue, le poste n'est pas non plus enregistré.
    carte = await _attribuer_carte_automatique(db, employe)

    await db.commit()
    await db.refresh(candidat)
    await db.refresh(employe)

    await manager.broadcast({
        "event": "poste_choisi",
        "employe_id": employe.id,
        "poste": poste.type_poste,
        "candidat": {"id": candidat.id, "nom": candidat.nom},
    })
    await manager.broadcast({
        "event": "carte_assignee",
        "employe_id": employe.id,
        "carte_uid": carte.uidcarte,
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "message": f"Carte {carte.uidcarte} attribuée automatiquement à {candidat.nom}.",
    })
    await manager.broadcast({
        "event": "employe_actif",
        "employe_id": employe.id,
        "poste": poste.type_poste,
        "message": (
            f"Félicitations ! Vous êtes maintenant employé en tant que {poste.type_poste}. "
            f"Votre carte ({carte.uidcarte}) vous a été attribuée automatiquement."
        ),
    })

    return await _avec_visage_enrole(db, candidat)


# --- Écran kiosque (sys_ecran) : secret statique, pas un JWT admin ---

def _verifier_secret_ecran(x_ecran_secret: str | None):
    if x_ecran_secret != settings.ECRAN_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Secret écran invalide")


@router.get("/ecran/tache-active")
async def tache_active_ecran(
    db: AsyncSession = Depends(get_db),
    x_ecran_secret: str | None = Header(default=None),
):
    """
    Route dédiée à l'écran kiosque. RECONNAISSANCE FACIALE DÉSACTIVÉE /
    ATTRIBUTION AUTOMATIQUE DE CARTE : comme la carte est maintenant
    attribuée automatiquement dans choisir_poste ci-dessus, il n'y a en
    principe plus jamais personne "en attente de carte" via ce chemin.
    Conservée telle quelle (inoffensive) pour compat / dépannage.
    """
    _verifier_secret_ecran(x_ecran_secret)

    stmt = (
        select(Candidat, Employe)
        .join(Employe, Employe.id == Candidat.employe_id)
        .where(
            Candidat.statut == "actif",
            Candidat.employe_id.is_not(None),
            Candidat.poste_attribue.is_not(None),
            Employe.carterfid_id.is_(None),
        )
    )
    ligne = (await db.execute(stmt)).first()

    if not ligne:
        return None

    candidat, employe = ligne
    return {
        "candidatId": candidat.id,
        "employeId": employe.id,
        "nom": candidat.nom,
        "poste": candidat.poste_attribue,
    }


@router.post("/ecran/attribuer-carte")
async def attribuer_carte_ecran(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    x_ecran_secret: str | None = Header(default=None),
):
    """
    Conservée pour compat / dépannage manuel (ex. si l'attribution
    automatique a échoué faute de carte libre et qu'on veut forcer après
    avoir libéré une carte). N'est plus le chemin normal.
    """
    _verifier_secret_ecran(x_ecran_secret)

    uidcarte = (payload or {}).get("uidcarte")
    if not uidcarte:
        raise HTTPException(400, "uidcarte manquant")

    carte = (
        await db.execute(select(Carterfid).where(Carterfid.uidcarte == uidcarte))
    ).scalar_one_or_none()
    if not carte:
        raise HTTPException(404, "Carte RFID non trouvée")

    deja_assignee = (
        await db.execute(select(Employe).where(Employe.carterfid_id == carte.id))
    ).scalar_one_or_none()
    if deja_assignee:
        raise HTTPException(409, "Cette carte est déjà assignée à un employé")

    stmt = (
        select(Candidat, Employe)
        .join(Employe, Employe.id == Candidat.employe_id)
        .where(
            Candidat.statut == "actif",
            Candidat.employe_id.is_not(None),
            Candidat.poste_attribue.is_not(None),
            Employe.carterfid_id.is_(None),
        )
    )
    ligne = (await db.execute(stmt)).first()
    if not ligne:
        raise HTTPException(
            409,
            "Aucun candidat en attente de carte.",
        )
    candidat, employe = ligne

    employe.carterfid_id = carte.id
    await db.commit()
    await db.refresh(employe)

    await manager.broadcast({
        "event": "carte_assignee",
        "employe_id": employe.id,
        "carte_uid": carte.uidcarte,
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "message": f"Carte remise à {candidat.nom}.",
    })

    return {
        "success": True,
        "message": "Carte assignée à l'employé",
        "employe_id": employe.id,
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "carte_uid": carte.uidcarte,
    }


# --- Admin uniquement ---

@router.get("", response_model=list[CandidatOut], dependencies=[Depends(require_admin)])
async def liste_candidats(db: AsyncSession = Depends(get_db)):
    stmt = select(Candidat).where(Candidat.statut != "historique").order_by(Candidat.heure_inscription)
    candidats = (await db.execute(stmt)).scalars().all()
    return [await _avec_visage_enrole(db, c) for c in candidats]


@router.get("/historique", response_model=list[CandidatOut], dependencies=[Depends(require_admin)])
async def historique(db: AsyncSession = Depends(get_db)):
    stmt = select(Candidat).where(Candidat.statut == "historique").order_by(Candidat.heure_retrait.desc())
    return (await db.execute(stmt)).scalars().all()


def _generer_matricule(candidat_id: int) -> str:
    """Matricule auto pour les employés promus depuis un candidat."""
    return f"CAND-{candidat_id:06d}"


@router.post("/{candidat_id}/virer", response_model=CandidatOut, dependencies=[Depends(require_admin)])
async def virer_manuellement(candidat_id: int, db: AsyncSession = Depends(get_db)):
    """
    Vire manuellement un candidat/employé (sans passer par la simulation).

    - Passe le candidat en "historique"
    - Passe l'employé en "Inactif"
    - Détache la carte RFID (elle redevient disponible pour un futur
      candidat, voir _attribuer_carte_automatique ci-dessus : c'est
      exactement le mécanisme de libération demandé)
    - Broadcast l'événement
    """
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")

    if candidat.statut not in ("actif", "attente"):
        raise HTTPException(409, "Ce candidat n'est plus actif ou en attente")

    # On récupère l'employé s'il existe
    employe = None
    if candidat.employe_id:
        employe = await db.get(Employe, candidat.employe_id)

    # 1. Candidat → historique
    candidat.statut = "historique"
    candidat.heure_retrait = datetime.now(timezone.utc)

    # 2. Employé → Inactif + détacher la carte
    if employe:
        employe.status = "Inactif"
        employe.carterfid_id = None          # libère la carte
        await nettoyer_biometrie_employe(db, employe.id)
        
    await db.commit()
    await db.refresh(candidat)

    # 3. Broadcast
    await manager.broadcast({
        "event": "vire_manuel",
        "message": f"{candidat.nom} a été viré manuellement.",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "employe_id": employe.id if employe else None,
    })

    return candidat

@router.post("/{candidat_id}/accepter", response_model=CandidatOut, dependencies=[Depends(require_admin)])
async def accepter(candidat_id: int, db: AsyncSession = Depends(get_db)):
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "attente":
        raise HTTPException(409, "Ce candidat n'est pas en attente")

    # Jusqu'à 4 candidats actifs en parallèle (plus d'index unique en BDD)
    MAX_ACTIFS = 4
    nb_actifs = (
        await db.execute(
            select(func.count()).select_from(Candidat).where(Candidat.statut == "actif")
        )
    ).scalar_one()
    if nb_actifs >= MAX_ACTIFS:
        raise HTTPException(
            409,
            f"Déjà {MAX_ACTIFS} candidats actifs. Retire-en un avant d'en accepter un autre.",
        )

    candidat.statut = "actif"
    candidat.heure_acceptation = datetime.now(timezone.utc)

    # L'employé est créé MAINTENANT, sans poste ni carte : le candidat
    # passe directement à /choisir-poste (plus d'étape d'enrôlement du
    # visage tant que la reconnaissance faciale est désactivée).
    employe = Employe(
        nom=candidat.nom,
        matricule=_generer_matricule(candidat.id),
        id_poste=None,
        carterfid_id=None,
        status="Actif",
        user_id=candidat.user_id,
        date_embauche=_aujourdhui(),
    )
    db.add(employe)
    await db.flush()
    candidat.employe_id = employe.id

    await db.commit()
    await db.refresh(candidat)

    await manager.broadcast({
        "event": "candidat_actif",
        "candidat": {"id": candidat.id, "nom": candidat.nom},
        "employe_id": employe.id,
        "message": "Veuillez choisir votre poste.",
    })

    return candidat
    
@router.post("/{candidat_id}/retirer", response_model=CandidatOut, dependencies=[Depends(require_admin)])
async def retirer(candidat_id: int, db: AsyncSession = Depends(get_db)):
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    if candidat.statut != "actif":
        raise HTTPException(409, "Ce candidat n'est pas actif")

    # Ne touche qu'au statut du candidat : l'employé créé lors de
    # l'acceptation (candidat.employe_id) reste intact dans la table employes.
    candidat.statut = "historique"
    candidat.heure_retrait = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(candidat)
    await manager.broadcast({"event": "retrait", "candidat_id": candidat.id})
    return candidat


@router.post("/vider-attente", dependencies=[Depends(require_admin)])
async def vider_attente(db: AsyncSession = Depends(get_db)):
    """Bouton panique : personne ne répond, on relance tout le monde."""
    await db.execute(
        update(Candidat).where(Candidat.statut == "attente").values(statut="historique")
    )
    await db.commit()
    return {"message": "File d'attente vidée"}

@router.delete("/{candidat_id}", status_code=204, dependencies=[Depends(require_admin)])
async def supprimer_candidat(candidat_id: int, db: AsyncSession = Depends(get_db)):
    """Supprime un candidat, peu importe son statut (spam, nom déplacé, etc.).
    N'efface pas l'employé éventuellement déjà créé (employe_id)."""
    candidat = await db.get(Candidat, candidat_id)
    if not candidat:
        raise HTTPException(404, "Candidat non trouvé")
    await db.delete(candidat)
    await db.commit()


@router.delete("/attente/tout", dependencies=[Depends(require_admin)])
async def supprimer_toute_attente(db: AsyncSession = Depends(get_db)):
    """Vide complètement la file d'attente (différent de vider-attente qui archive)."""
    result = await db.execute(delete(Candidat).where(Candidat.statut == "attente"))
    await db.commit()
    return {"message": f"{result.rowcount} candidat(s) supprimé(s)"}

@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats(db: AsyncSession = Depends(get_db)):
    en_attente = (await db.execute(
        select(func.count()).select_from(Candidat).where(Candidat.statut == "attente")
    )).scalar()
    deja_passes = (await db.execute(
        select(func.count()).select_from(Candidat).where(Candidat.statut == "historique")
    )).scalar()
    return {"en_attente": en_attente, "deja_passes": deja_passes}
