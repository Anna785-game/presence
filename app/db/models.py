import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Poste(Base):
    __tablename__ = "postes"

    id: Mapped[int] = mapped_column(primary_key=True)
    type_poste: Mapped[str | None] = mapped_column(String(30))
    poids: Mapped[int] = mapped_column(Integer, default=1)

    employes: Mapped[list["Employe"]] = relationship(back_populates="poste")

class Carterfid(Base):
    __tablename__ = "carterfid"

    id: Mapped[int] = mapped_column(primary_key=True)
    uidcarte: Mapped[str | None] = mapped_column(String(30), unique=True, index=True)
    couleur: Mapped[str | None] = mapped_column(String(15))
    isentree: Mapped[bool | None] = mapped_column(Boolean, default=False)

    employe: Mapped["Employe"] = relationship(back_populates="carterfid", uselist=False)


class Employe(Base):
    __tablename__ = "employes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str | None] = mapped_column(String(20))
    prenom: Mapped[str | None] = mapped_column(String(20))
    matricule: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    date_embauche: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(13), default="Actif")  # Actif / Inactif

    # Lien vers l'utilisateur Supabase Auth (nullable : un employé n'a pas forcément de compte)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # NULLABLE : un employé est désormais créé dès l'acceptation du candidat,
    # AVANT le choix du poste. Le poste n'est attribué qu'après l'enrôlement
    # du visage, quand le candidat le choisit lui-même depuis son téléphone
    # (voir app/routers/candidats.py::choisir_poste).
    id_poste: Mapped[int | None] = mapped_column(ForeignKey("postes.id"), nullable=True)
    poste: Mapped["Poste | None"] = relationship(back_populates="employes")

    # NULLABLE désormais : un candidat promu employé n'a pas encore de carte RFID
    # au moment de sa création. Elle est assignée plus tard via /cartes.
    carterfid_id: Mapped[int | None] = mapped_column(
        ForeignKey("carterfid.id"), nullable=True, unique=True
    )
    carterfid: Mapped["Carterfid | None"] = relationship(back_populates="employe")

    presences: Mapped[list["Presence"]] = relationship(back_populates="employe")
    absences: Mapped[list["Absence"]] = relationship(back_populates="employe")


class Presence(Base):
    __tablename__ = "presences"

    id: Mapped[int] = mapped_column(primary_key=True)
    datedujour: Mapped[date] = mapped_column(Date, nullable=False)
    statut: Mapped[str | None] = mapped_column(String(50))  # present / en retard / ok
    dureetravail: Mapped[int | None] = mapped_column(Integer)  # en minutes

    id_employe: Mapped[int] = mapped_column(ForeignKey("employes.id"), nullable=False)
    employe: Mapped["Employe"] = relationship(back_populates="presences")


class PresenceEntree(Base):
    __tablename__ = "presence_entree"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    heure_entree: Mapped[time] = mapped_column(Time, nullable=False)
    ack: Mapped[bool | None] = mapped_column(Boolean, default=False)

    id_employe: Mapped[int] = mapped_column(ForeignKey("employes.id"))
    employe: Mapped["Employe"] = relationship()


class Sortie(Base):
    __tablename__ = "sorties"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    heure_sortie: Mapped[time] = mapped_column(Time, nullable=False)

    id_employe: Mapped[int] = mapped_column(ForeignKey("employes.id"), nullable=False)
    employe: Mapped["Employe"] = relationship()


class Absence(Base):
    __tablename__ = "absences"

    id: Mapped[int] = mapped_column(primary_key=True)
    dateabsence: Mapped[date] = mapped_column(Date, nullable=False)
    raison: Mapped[str | None] = mapped_column(String(255))

    idemploye: Mapped[int] = mapped_column(ForeignKey("employes.id"), nullable=False)
    employe: Mapped["Employe"] = relationship(back_populates="absences")

class Candidat(Base):
    __tablename__ = "candidats"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(50), nullable=False)
    heure_inscription: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    statut: Mapped[str] = mapped_column(String(12), default="attente")  # attente / actif / historique
    poste_attribue: Mapped[str | None] = mapped_column(String(30))
    heure_acceptation: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heure_retrait: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_inscription: Mapped[str | None] = mapped_column(String(45))

    # Lien vers le compte Supabase Auth créé au register (fusion register / inscription)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Une fois le candidat accepté (poste attribué), il est promu en Employe.
    # Ce lien persiste même si le candidat repasse en "historique" ensuite :
    # l'employé, lui, reste dans la table employes.
    employe_id: Mapped[int | None] = mapped_column(ForeignKey("employes.id"), nullable=True)
    employe: Mapped["Employe | None"] = relationship()


class FaceEncoding(Base):
    """
    Un seul encoding facial par employé (relation 1:1), utilisé UNIQUEMENT
    pour la vérification 1:1 carte <-> visage (jamais une recherche parmi
    tous les employés).

    On ne stocke pas la photo d'origine : uniquement les 128 nombres
    flottants nécessaires à la comparaison. C'est suffisant pour la démo
    et évite de conserver des images de visages en base.
    """
    __tablename__ = "face_encodings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ondelete="CASCADE" : si un employé est un jour supprimé en base (DELETE
    # /employes/{id}), son encoding disparaît avec lui automatiquement.
    # Mais l'essentiel pour la sécurité de la démo, c'est le nettoyage
    # EXPLICITE quand l'employé passe "Inactif" (voir app/core/biometrie_hooks.py) :
    # un employé viré reste en base mais ne doit plus pouvoir s'authentifier.
    employe_id: Mapped[int] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    encoding: Mapped[list] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    employe: Mapped["Employe"] = relationship()
