import base64
import hashlib
import hmac
import json
import os
import secrets

from cryptography.fernet import Fernet

from .config import get_settings


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return _hash(token)


def create_token() -> str:
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return "pbkdf2_sha256$240000$%s$%s" % (
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_json(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_json(encrypted: str) -> dict:
    return json.loads(_fernet().decrypt(encrypted.encode("ascii")).decode("utf-8"))
