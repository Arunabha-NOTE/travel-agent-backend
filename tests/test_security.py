from passlib.context import CryptContext

from app.core.security import hash_password, verify_password


def test_hash_password_supports_passwords_longer_than_bcrypt_limit() -> None:
    password = "correct horse battery staple " * 4

    hashed_password = hash_password(password)

    assert hashed_password.startswith("$bcrypt-sha256$")
    assert verify_password(password, hashed_password)


def test_verify_password_accepts_existing_bcrypt_hashes() -> None:
    legacy_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    password = "legacy-password"
    legacy_hash = legacy_context.hash(password)

    assert verify_password(password, legacy_hash)
