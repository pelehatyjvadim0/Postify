"""Хранилище пользователей, запросов на вход и сессий.

Всё синхронное, как остальные репозитории проекта: цикл опроса бота вызывает
эти методы через ``asyncio.to_thread``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select

from postify.domain.auth.models import (
    APPROVED,
    CONFIRMATION,
    LoginRequest,
    User,
)
from postify.infrastructure.database.models import (
    ContentProjectModel,
    LoginRequestModel,
    UserModel,
    UserSessionModel,
    UserSettingsModel,
)


class SqlAlchemyUserRepository:
    """Пользователи, запросы на вход, сессии и владелец проекта."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # --- пользователи -----------------------------------------------------

    def user_by_telegram_id(self, telegram_user_id: str) -> User | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(UserModel).where(
                    UserModel.telegram_user_id == telegram_user_id
                )
            )
            return _user(model) if model is not None else None

    def user(self, user_id: int) -> User | None:
        with self._session_factory() as session:
            model = session.get(UserModel, user_id)
            return _user(model) if model is not None else None

    def ensure_user(
        self,
        *,
        telegram_user_id: str,
        telegram_username: str,
        display_name: str,
        now: datetime,
    ) -> User:
        """Заводит пользователя при первом входе, дальше обновляет профиль.

        Отдельной регистрации нет, поэтому первый подтверждённый вход и есть
        создание аккаунта.
        """
        with self._session_factory() as session:
            try:
                model = session.scalar(
                    select(UserModel)
                    .where(UserModel.telegram_user_id == telegram_user_id)
                    .with_for_update()
                )
                if model is None:
                    model = UserModel(
                        telegram_user_id=telegram_user_id,
                        telegram_username=telegram_username,
                        display_name=display_name,
                        created_at=now,
                        last_login_at=now,
                        is_active=True,
                    )
                    session.add(model)
                else:
                    model.telegram_username = telegram_username
                    model.display_name = display_name
                    model.last_login_at = now
                session.commit()
                session.refresh(model)
                return _user(model)
            except BaseException:
                session.rollback()
                raise

    def common_prompt(self, user_id: int) -> str:
        """Общий промпт пользователя; до первой правки его просто нет."""
        with self._session_factory() as session:
            value = session.scalar(
                select(UserSettingsModel.common_prompt).where(
                    UserSettingsModel.user_id == user_id
                )
            )
            return value or ""

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
        with self._session_factory() as session:
            try:
                model = LoginRequestModel(
                    telegram_token=telegram_token,
                    browser_token=browser_token,
                    status="pending",
                    ip=ip,
                    created_at=now,
                    expires_at=expires_at,
                )
                session.add(model)
                session.commit()
                session.refresh(model)
                return _login_request(model)
            except BaseException:
                session.rollback()
                raise

    def login_request_by_browser_token(self, browser_token: str) -> LoginRequest | None:
        return self._login_request(LoginRequestModel.browser_token, browser_token)

    def login_request_by_telegram_token(
        self, telegram_token: str
    ) -> LoginRequest | None:
        return self._login_request(LoginRequestModel.telegram_token, telegram_token)

    def _login_request(self, column, value: str) -> LoginRequest | None:
        with self._session_factory() as session:
            model = session.scalar(select(LoginRequestModel).where(column == value))
            return _login_request(model) if model is not None else None

    def mark_confirmation(
        self,
        *,
        telegram_token: str,
        telegram_user_id: str,
        telegram_username: str,
        display_name: str,
        now: datetime,
    ) -> LoginRequest | None:
        """Бот получил /start: запоминаем, кто именно просит подтверждения.

        Возвращает ``None``, если запрос истёк или уже вышел из ``pending`` —
        повторный ``/start`` по одному токену ничего не переписывает.
        """
        with self._session_factory() as session:
            try:
                model = session.scalar(
                    select(LoginRequestModel)
                    .where(LoginRequestModel.telegram_token == telegram_token)
                    .with_for_update()
                )
                if model is None or model.status != "pending" or model.expires_at <= now:
                    session.rollback()
                    return None
                model.status = CONFIRMATION
                model.telegram_user_id = telegram_user_id
                model.telegram_username = telegram_username
                model.display_name = display_name
                session.commit()
                session.refresh(model)
                return _login_request(model)
            except BaseException:
                session.rollback()
                raise

    def decide(
        self, *, telegram_token: str, status: str, telegram_user_id: str, now: datetime
    ) -> LoginRequest | None:
        """Фиксирует нажатие кнопки. Чужой telegram_user_id решение не меняет."""
        with self._session_factory() as session:
            try:
                model = session.scalar(
                    select(LoginRequestModel)
                    .where(LoginRequestModel.telegram_token == telegram_token)
                    .with_for_update()
                )
                if (
                    model is None
                    or model.status != CONFIRMATION
                    or model.expires_at <= now
                    or model.telegram_user_id != telegram_user_id
                ):
                    session.rollback()
                    return None
                model.status = status
                model.decided_at = now
                session.commit()
                session.refresh(model)
                return _login_request(model)
            except BaseException:
                session.rollback()
                raise

    def consume_login_request(self, request_id: int) -> None:
        """Гасит запрос: вход выполнен, вторая cookie по нему не выдаётся."""
        with self._session_factory() as session:
            try:
                session.execute(
                    delete(LoginRequestModel).where(LoginRequestModel.id == request_id)
                )
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def purge_expired(self, now: datetime) -> None:
        """Уборка истёкших запросов и сессий; вызывается на каждой попытке входа."""
        with self._session_factory() as session:
            try:
                session.execute(
                    delete(LoginRequestModel).where(LoginRequestModel.expires_at <= now)
                )
                session.execute(
                    delete(UserSessionModel).where(UserSessionModel.expires_at <= now)
                )
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def failed_attempts(self, *, ip: str | None, since: datetime) -> int:
        """Незавершённые попытки входа с IP за окно.

        Успешный вход удаляет свой запрос, поэтому в счётчик попадают только
        неудачные и брошенные — как счётчик failures в образце.
        """
        if ip is None:
            return 0
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(LoginRequestModel)
                    .where(
                        LoginRequestModel.ip == ip,
                        LoginRequestModel.created_at >= since,
                        LoginRequestModel.status != APPROVED,
                    )
                )
                or 0
            )

    def active_login_requests(self, now: datetime) -> int:
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(LoginRequestModel)
                    .where(LoginRequestModel.expires_at > now)
                )
                or 0
            )

    # --- сессии -----------------------------------------------------------

    def create_session(
        self, *, user_id: int, token_hash: str, now: datetime, expires_at: datetime
    ) -> None:
        with self._session_factory() as session:
            try:
                session.add(
                    UserSessionModel(
                        user_id=user_id,
                        token_hash=token_hash,
                        created_at=now,
                        expires_at=expires_at,
                    )
                )
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def session_user(self, *, token_hash: str, now: datetime) -> User | None:
        """Пользователь действующей сессии; истёкшая и отключённый — не в счёт."""
        with self._session_factory() as session:
            model = session.scalar(
                select(UserModel)
                .join(UserSessionModel, UserSessionModel.user_id == UserModel.id)
                .where(
                    UserSessionModel.token_hash == token_hash,
                    UserSessionModel.expires_at > now,
                    UserModel.is_active.is_(True),
                )
            )
            return _user(model) if model is not None else None

    def delete_session(self, token_hash: str) -> None:
        with self._session_factory() as session:
            try:
                session.execute(
                    delete(UserSessionModel).where(
                        UserSessionModel.token_hash == token_hash
                    )
                )
                session.commit()
            except BaseException:
                session.rollback()
                raise

    # --- владение проектом ------------------------------------------------

    def project_owner(self, project_id: int) -> int | None:
        """Владелец проекта или ``None``, если проекта нет.

        Чужой и несуществующий проект веб-слой отдаёт одинаково — 404.
        """
        with self._session_factory() as session:
            return session.scalar(
                select(ContentProjectModel.owner_id).where(
                    ContentProjectModel.id == project_id
                )
            )


def _user(model: UserModel) -> User:
    return User(
        id=model.id,
        telegram_user_id=model.telegram_user_id,
        telegram_username=model.telegram_username,
        display_name=model.display_name,
        created_at=model.created_at,
        last_login_at=model.last_login_at,
        is_active=model.is_active,
    )


def _login_request(model: LoginRequestModel) -> LoginRequest:
    return LoginRequest(
        id=model.id,
        telegram_token=model.telegram_token,
        browser_token=model.browser_token,
        status=model.status,
        telegram_user_id=model.telegram_user_id,
        telegram_username=model.telegram_username,
        display_name=model.display_name,
        ip=model.ip,
        created_at=model.created_at,
        expires_at=model.expires_at,
        decided_at=model.decided_at,
    )
