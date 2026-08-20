from datetime import date, datetime, time
from pydantic import BaseModel, ConfigDict
from uuid import UUID

# ---------- Poste ----------
class PosteBase(BaseModel):
    type_poste: str | None = None
    poids: int = 1

class PosteOut(PosteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int

class PosteCreate(PosteBase):
    pass

# ---------- Carterfid ----------
class CarterfidBase(BaseModel):
    uidcarte: str | None = None
    couleur: str | None = None


class CarterfidCreate(CarterfidBase):
    pass


class CarterfidOut(CarterfidBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    isentree: bool | None = False


# ---------- Employe ----------
class EmployeBase(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    matricule: str
    date_embauche: date | None = None
    status: str | None = "Actif"


class EmployeCreate(EmployeBase):
    id_poste: int | None = None
    carterfid_id: int | None = None
    user_id: UUID | None = None          # ← changé


class EmployeUpdate(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    date_embauche: date | None = None
    status: str | None = None
    id_poste: int | None = None
    carterfid_id: int | None = None
    user_id: UUID | None = None          # ← changé


class EmployeOut(EmployeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_poste: int | None = None
    carterfid_id: int | None = None
    user_id: UUID | None = None          # ← changé

# ---------- Presence ----------
class PresenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    datedujour: date
    statut: str | None
    dureetravail: int | None
    id_employe: int


# ---------- Absence ----------
class AbsenceCreate(BaseModel):
    idemploye: int
    dateabsence: date
    raison: str | None = None


class AbsenceOut(AbsenceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Pointage (badge) ----------
class BadgeScan(BaseModel):
    uidcarte: str


class PointageResult(BaseModel):
    success: bool
    action: str  # "entree" | "sortie"
    employe_id: int
    heure: time


# ---------- Auth ----------
class UserAuth(BaseModel):
    """Utilisé pour /auth/login (email + mot de passe seulement)."""
    email: str
    password: str


class RegisterRequest(BaseModel):
    """
    Utilisé pour /auth/register.
    Fusionne la création de compte ET l'inscription candidat :
    le `nom` saisi ici devient directement le nom du candidat (puis de
    l'employé si le candidat est accepté plus tard) — pas de ressaisie.
    """
    email: str
    password: str
    nom: str


# ---------- Link compte / employé ----------
class LinkEmployeRequest(BaseModel):
    matricule: str
    

class CandidatInscription(BaseModel):
    nom: str


class CandidatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    statut: str
    heure_inscription: datetime
    poste_attribue: str | None = None
    # Rempli une fois le candidat accepté et promu en employé.
    # Reste renseigné même après passage en "historique".
    employe_id: int | None = None
    # True une fois que le candidat a enrôlé son visage depuis son téléphone
    # (voir /api/biometrie/enroll-public). Sert de signal au front visiteur
    # pour savoir s'il doit encore aller enrôler son visage, ou s'il peut
    # directement choisir son poste (/candidats/{id}/choisir-poste).
    visage_enrole: bool = False
