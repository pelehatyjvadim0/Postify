"""Репозиторий входа в памяти: те же инварианты, что у SQLAlchemy-версии.

Держится в одном месте, чтобы действия и веб-слой проверялись против
одинакового поведения хранилища.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from postify.domain.auth.models import LoginRequest, User


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.requests: dict[int, LoginRequest] = {}
        self.sessions: dict[str, tuple[int, datetime]] = {}
        self.prompts: dict[int, str] = {}
        self.owners: dict[int, int] = {}
        # Отдельные последовательности, как отдельные таблицы в базе.
        self._next_user_id = 1
        self._next_request_id = 1

    def _user_identity(self) -> int:
        value = self._next_user_id
        self._next_user_id += 1
        return value

    def _request_identity(self) -> int:
        value = self._next_request_id
        self._next_request_id += 1
        return value

    # --- пользователи -----------------------------------------------------

    def user_by_telegram_id(self, telegram_user_id: str) -> User | None:
        for user in self.users.values():
            if user.telegram_user_id == telegram_user_id:
                return user
        return None

    def user(self, user_id: int) -> User | None:
        return self.users.get(user_id)

    def ensure_user(
        self,
        *,
        telegram_user_id: str,
        telegram_username: str,
        display_name: str,
        now: datetime,
    ) -> User:
        existing = self.user_by_telegram_id(telegram_user_id)
        if existing is None:
            user = User(
                id=self._user_identity(),
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                display_name=display_name,
                created_at=now,
                last_login_at=now,
                is_active=True,
            )
        else:
            user = replace(
                existing,
                telegram_username=telegram_username,
                display_name=display_name,
                last_login_at=now,
            )
        self.users[user.id] = user
        return user

    def common_prompt(self, user_id: int) -> str:
        return self.prompts.get(user_id, "")

    # --- запросы на вход --------------------------------------------------

    def create_login_request(
        self,
        *,
        telegram_token: str,
        browser_token: str,
        ip: str | None,
        now: datetime,
        expires_at: datetime,
    ) -> LoginRequest:
        request = LoginRequest(
            id=self._request_identity(),
            telegram_token=telegram_token,
            browser_token=browser_token,
            status="pending",
            telegram_user_id=None,
            telegram_username=None,
            display_name=None,
            ip=ip,
            created_at=now,
            expires_at=expires_at,
            decided_at=None,
        )
        self.requests[request.id] = request
        return request

    def login_request_by_browser_token(self, browser_token: str) -> LoginRequest | None:
        return self._find("browser_token", browser_token)

    def login_request_by_telegram_token(
        self, telegram_token: str
    ) -> LoginRequest | None:
        return self._find("telegram_token", telegram_token)

    def _find(self, field: str, value: str) -> LoginRequest | None:
        for request in self.requests.values():
            if getattr(request, field) == value:
                return request
        return None

    def mark_confirmation(
        self,
        *,
        telegram_token: str,
        telegram_user_id: str,
        telegram_username: str,
        display_name: str,
        now: datetime,
    ) -> LoginRequest | None:
        request = self._find("telegram_token", telegram_token)
        if request is None or request.status != "pending" or request.expires_at <= now:
            return None
        updated = replace(
            request,
            status="confirmation",
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            display_name=display_name,
        )
        self.requests[request.id] = updated
        return updated

    def decide(
        self, *, telegram_token: str, status: str, telegram_user_id: str, now: datetime
    ) -> LoginRequest | None:
        request = self._find("telegram_token", telegram_token)
        if (
            request is None
            or request.status != "confirmation"
            or request.expires_at <= now
            or request.telegram_user_id != telegram_user_id
        ):
            return None
        updated = replace(request, status=status, decided_at=now)
        self.requests[request.id] = updated
        return updated

    def consume_login_request(self, request_id: int) -> None:
        self.requests.pop(request_id, None)

    def purge_expired(self, now: datetime) -> None:
        for identifier, request in list(self.requests.items()):
            if request.expires_at <= now:
                del self.requests[identifier]
        for token, (_, expires_at) in list(self.sessions.items()):
            if expires_at <= now:
                del self.sessions[token]

    def failed_attempts(self, *, ip: str | None, since: datetime) -> int:
        if ip is None:
            return 0
        return sum(
            1
            for request in self.requests.values()
            if request.ip == ip
            and request.created_at >= since
            and request.status != "approved"
        )

    def active_login_requests(self, now: datetime) -> int:
        return sum(1 for request in self.requests.values() if request.expires_at > now)

    # --- сессии -----------------------------------------------------------

    def create_session(
        self, *, user_id: int, token_hash: str, now: datetime, expires_at: datetime
    ) -> None:
        self.sessions[token_hash] = (user_id, expires_at)

    def session_user(self, *, token_hash: str, now: datetime) -> User | None:
        found = self.sessions.get(token_hash)
        if found is None or found[1] <= now:
            return None
        user = self.users.get(found[0])
        return user if user is not None and user.is_active else None

    def delete_session(self, token_hash: str) -> None:
        self.sessions.pop(token_hash, None)

    # --- владение проектом ------------------------------------------------

    def project_owner(self, project_id: int) -> int | None:
        return self.owners.get(project_id)
