"""Génère une paire de clés VAPID pour les push notifications web.

À exécuter une seule fois en local. Copier les valeurs imprimées dans Render
comme variables d'environnement :
    VAPID_PRIVATE_KEY  = <bloc PEM multi-lignes>
    VAPID_PUBLIC_KEY   = <chaîne b64 url-safe sans padding>
    VAPID_CONTACT      = mailto:<ton-email>

⚠️ NE PAS commiter la sortie. La clé privée doit rester secrète.
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def main() -> None:
    v = Vapid01()
    v.generate_keys()

    private_pem = v.private_pem().decode()

    public_uncompressed = v.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(public_uncompressed).rstrip(b"=").decode()

    sep = "=" * 60
    print(sep)
    print("VAPID_PRIVATE_KEY (bloc PEM, copier tel quel dans Render) :")
    print(sep)
    print(private_pem)

    print(sep)
    print("VAPID_PUBLIC_KEY (b64 url-safe, sans padding) :")
    print(sep)
    print(public_b64)

    print()
    print("Ajoute aussi VAPID_CONTACT=mailto:<ton-email> dans Render.")


if __name__ == "__main__":
    main()
