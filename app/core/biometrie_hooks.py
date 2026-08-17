# app/core/biometrie_hooks.py
"""
Petit helper centralisé pour nettoyer les données biométriques d'un employé
dès qu'il passe "Inactif", quel que soit le chemin emprunté :

- app/routers/candidats.py  -> virer_manuellement()
- app/routers/simulation.py -> run_simulation() (viré en cours de route ET
  fin normale au jour 7)

Sans ce nettoyage, un encoding facial resterait utilisable en base même
après licenciement (le check `employe.status != "Actif"` dans /verify
bloquerait quand même l'accès, mais mieux vaut supprimer la donnée
biométrique elle-même : c'est la donnée la plus sensible du système).

Import prévu dans les 3 endroits ci-dessus :

    from app.core.biometrie_hooks import nettoyer_biometrie_employe

Puis appeler juste avant le `await db.commit()` qui passe employe.status
à "Inactif" :

    await nettoyer_biometrie_employe(db, employe.id)
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FaceEncoding


async def nettoyer_biometrie_employe(db: AsyncSession, employe_id: int) -> bool:
    """Supprime l'encoding facial de l'employé s'il existe.
    Retourne True si une ligne a été supprimée, False sinon.
    N'appelle PAS commit() : à faire dans le même commit que le
    changement de statut de l'employé, pour rester atomique.
    """
    existant = (
        await db.execute(select(FaceEncoding).where(FaceEncoding.employe_id == employe_id))
    ).scalar_one_or_none()
    if existant:
        await db.delete(existant)
        return True
    return False
