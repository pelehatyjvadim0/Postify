from typing import Protocol

from postify.domain.projects.models import ContentProject


class ProjectRepository(Protocol):
    def get(self, project_id: int) -> ContentProject: ...

    def save(self, project: ContentProject) -> ContentProject: ...

