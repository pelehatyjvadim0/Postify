from __future__ import annotations

from collections.abc import Sequence
import json
from sqlalchemy import text

from postify.application.validation.models import ProjectRule
from postify.domain.posts.models import InvalidPostTransition


class SqlAlchemyRulesRepository:
    def __init__(self, session_factory):
        self.sf = session_factory

    def list_rules(self, project_id: int, *, enabled_only: bool = False) -> tuple[ProjectRule, ...]:
        with self.sf() as session:
            rows = session.execute(text("SELECT * FROM project_rules WHERE project_id=:p AND (:e=false OR enabled) ORDER BY position,id"), {"p": project_id, "e": enabled_only}).mappings().all()
        return tuple(ProjectRule(r["id"], r["project_id"], r["text"], r["severity"], r["enabled"], r["origin"], r["position"]) for r in rows)

    def replace_rules(self, project_id: int, rules: Sequence[ProjectRule]) -> tuple[ProjectRule, ...]:
        with self.sf() as session:
            with session.begin():
                session.execute(text("DELETE FROM project_rules WHERE project_id=:p"), {"p": project_id})
                for pos, rule in enumerate(rules):
                    session.execute(text("INSERT INTO project_rules(project_id,text,severity,enabled,origin,position) VALUES (:p,:t,:s,:e,:o,:i)"), {"p": project_id, "t": rule.text, "s": rule.severity, "e": rule.enabled, "o": rule.origin, "i": pos})
        return self.list_rules(project_id)


class SqlAlchemyValidationJournal:
    def __init__(self, session_factory):
        self.sf = session_factory

    def save(self, post_id: int, *, iteration: int, report, now, expected_draft=None) -> None:
        with self.sf() as session:
            with session.begin():
                if expected_draft is not None:
                    current = session.execute(text(
                        "SELECT post_text,media_path,updated_at,status FROM posts WHERE id=:p FOR UPDATE"
                    ), {"p": post_id}).one_or_none()
                    if current is None or current.status != "needs_review" or tuple(current[:3]) != expected_draft:
                        raise InvalidPostTransition("Пост изменился во время проверки. Обновите страницу")
                if iteration == 0:
                    # Новая генерация того же поста начинает новый прогон и не
                    # должна показывать последнюю итерацию прежнего прогона.
                    session.execute(text("DELETE FROM validation_reports WHERE post_id=:p"), {"p": post_id})
                else:
                    session.execute(text("DELETE FROM validation_reports WHERE post_id=:p AND iteration=:i"), {"p": post_id, "i": iteration})
                for layer in report.layers:
                    session.execute(text("INSERT INTO validation_reports(post_id,iteration,layer,passed,details,created_at) VALUES (:p,:i,:l,:ok,CAST(:d AS jsonb),:n)"), {"p": post_id, "i": iteration, "l": layer.get("layer"), "ok": bool(layer.get("passed")), "d": json.dumps(dict(layer), ensure_ascii=False), "n": now})

    def report(self, post_id: int):
        with self.sf() as session:
            rows = session.execute(text("SELECT iteration,layer,passed,details FROM validation_reports WHERE post_id=:p AND iteration=(SELECT max(iteration) FROM validation_reports WHERE post_id=:p) ORDER BY CASE layer WHEN 'format' THEN 1 WHEN 'rules' THEN 2 WHEN 'grounding' THEN 3 WHEN 'image' THEN 4 END"), {"p": post_id}).mappings().all()
            max_iteration = session.execute(text("SELECT max(iteration) FROM validation_reports WHERE post_id=:p"), {"p": post_id}).scalar()
        if max_iteration is None:
            return None
        layers = [dict(r["details"]) for r in rows]
        return {"passed": all(r["passed"] for r in rows), "iterations": int(max_iteration), "layers": layers}

    def reports(self, post_ids):
        ids = tuple(dict.fromkeys(post_ids))
        if not ids:
            return {}
        with self.sf() as session:
            rows = session.execute(text("SELECT r.post_id,r.iteration,r.passed,r.details FROM validation_reports r JOIN (SELECT post_id,max(iteration) iteration FROM validation_reports WHERE post_id=ANY(:ids) GROUP BY post_id) latest USING(post_id,iteration) ORDER BY r.post_id,CASE r.layer WHEN 'format' THEN 1 WHEN 'rules' THEN 2 WHEN 'grounding' THEN 3 WHEN 'image' THEN 4 END"), {"ids": list(ids)}).mappings().all()
        result = {}
        for row in rows:
            report = result.setdefault(row["post_id"], {"passed": True, "iterations": row["iteration"], "layers": []})
            report["passed"] = report["passed"] and row["passed"]
            report["layers"].append(dict(row["details"]))
        return result
