from sqlalchemy import text


class SqlAlchemyTelegramSourceState:
    """Keep the first history cutoff; advance only through committed candidates."""

    def __init__(self, session_factory, project_id: int, source_connection_id: int):
        self._session_factory = session_factory
        self._project_id = project_id
        self._source_connection_id = source_connection_id

    def last_message_id(self, group_id: str) -> int | None:
        with self._session_factory() as session:
            return session.execute(text("""
                SELECT max(message_id) FROM (
                SELECT initial_after_message_id AS message_id FROM telegram_source_state
                WHERE project_id=:project AND source_connection_id=:connection AND group_id=:group
                UNION ALL
                SELECT max(CASE
                    WHEN jsonb_typeof(raw_payload->'message_id') = 'number'
                     AND raw_payload->>'message_id' ~ '^[0-9]{1,19}$'
                    THEN CASE
                        WHEN (raw_payload->>'message_id')::numeric BETWEEN 1 AND 9223372036854775807
                        THEN (raw_payload->>'message_id')::bigint
                    END
                END)
                FROM candidates
                WHERE project_id=:project AND source_connection_id=:connection
                  AND source_name='telegram_group'
                  AND raw_payload->>'group_id'=:group
                ) AS committed_state
            """), {
                "project": self._project_id,
                "connection": self._source_connection_id,
                "group": group_id,
            }).scalar_one()

    def initialize(self, group_id: str, after_message_id: int) -> int:
        if type(after_message_id) is not int or not 0 <= after_message_id <= 9223372036854775807:
            raise ValueError("initial_after_message_id must be a nonnegative bigint")
        params = {"project": self._project_id, "connection": self._source_connection_id,
                  "group": group_id, "after": after_message_id}
        with self._session_factory() as session:
            with session.begin():
                session.execute(text("""
                    INSERT INTO telegram_source_state
                        (project_id,source_connection_id,group_id,initial_after_message_id)
                    VALUES (:project,:connection,:group,:after)
                    ON CONFLICT (project_id,source_connection_id,group_id) DO NOTHING
                """), params)
                baseline = session.execute(text("""
                    SELECT initial_after_message_id FROM telegram_source_state
                    WHERE project_id=:project AND source_connection_id=:connection AND group_id=:group
                """), params).scalar_one()
        return baseline
