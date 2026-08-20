import pytest
from cryptography.fernet import Fernet

from postify.infrastructure.security.secrets import SecretCipher


def test_secret_cipher_round_trip_does_not_keep_plaintext() -> None:
    cipher = SecretCipher(Fernet.generate_key().decode())

    encrypted = cipher.encrypt("123:telegram-token")

    assert encrypted != "123:telegram-token"
    assert "telegram-token" not in encrypted
    assert cipher.decrypt(encrypted) == "123:telegram-token"


def test_secret_cipher_rejects_invalid_key_without_echoing_it() -> None:
    invalid = "super-secret-but-invalid"

    with pytest.raises(ValueError, match="ключ шифрования") as captured:
        SecretCipher(invalid)

    assert invalid not in str(captured.value)


def test_secret_cipher_rejects_tampered_value_with_safe_error() -> None:
    cipher = SecretCipher(Fernet.generate_key().decode())

    with pytest.raises(ValueError, match="расшифровать") as captured:
        cipher.decrypt("not-a-fernet-value")

    assert "not-a-fernet-value" not in str(captured.value)
