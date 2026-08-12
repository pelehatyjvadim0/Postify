from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("Некорректный ключ шифрования") from None

    def encrypt(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("Секрет не может быть пустым")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise ValueError("Не удалось расшифровать секрет") from None

