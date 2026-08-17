# app/core/face_client.py
"""
Remplace l'import direct de face_recognition côté Render.
Ce module ne fait AUCUN calcul : il appelle ton face_server (ton PC),
exposé via le tunnel, en HTTP.

Variables d'environnement à ajouter sur Render :
    FACE_SERVER_URL     -> ex. https://xxxx.trycloudflare.com
    FACE_SHARED_SECRET  -> le même secret que dans face_server/run.sh

Si ton PC est éteint ou le tunnel coupé, ces appels lèveront une
httpx.HTTPError / TimeoutException : à toi de décider si tu veux
renvoyer un 503 "biométrie indisponible" plutôt qu'un crash générique
(voir gestion des erreurs dans le router).
"""
import httpx

from app.core.config import settings

SEUIL_DEFAUT = 0.4


class AucunVisageDetecte(Exception):
    pass


class PlusieursVisagesDetectes(Exception):
    pass


class FaceServerIndisponible(Exception):
    """Le PC local / le tunnel ne répond pas."""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.FACE_SERVER_URL,
        headers={"X-Face-Secret": settings.FACE_SHARED_SECRET},
        timeout=15.0,  # le PC local + tunnel peut être plus lent qu'un appel interne
    )


async def image_bytes_vers_encoding(image_bytes: bytes) -> list[float]:
    try:
        async with _client() as client:
            resp = await client.post(
                "/encode",
                files={"photo": ("photo.jpg", image_bytes, "image/jpeg")},
            )
    except httpx.HTTPError as e:
        raise FaceServerIndisponible(str(e))

    if resp.status_code == 422:
        detail = resp.json().get("detail", "")
        if "Plusieurs" in detail:
            raise PlusieursVisagesDetectes(detail)
        raise AucunVisageDetecte(detail)
    resp.raise_for_status()
    return resp.json()["encoding"]


async def visage_correspond(
    encoding_reference: list[float],
    encoding_candidat: list[float],
    seuil: float = SEUIL_DEFAUT,
) -> tuple[bool, float]:
    try:
        async with _client() as client:
            resp = await client.post(
                "/compare",
                json={
                    "encoding_a": encoding_reference,
                    "encoding_b": encoding_candidat,
                    "seuil": seuil,
                },
            )
    except httpx.HTTPError as e:
        raise FaceServerIndisponible(str(e))

    resp.raise_for_status()
    data = resp.json()
    return data["match"], data["distance"]
