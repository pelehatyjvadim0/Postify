"""Сценарии пула изображений.

Загрузка, подпись, перевыпуск подписи и подбор шортлиста. Ни один модуль здесь
не знает про HTTP и не ходит к провайдеру напрямую: подписи и эмбеддинги идут
через шлюз вызовов модели (``application/ai/gateway.py``).
"""

from postify.application.media.captioning import (
    CaptionMedia,
    CaptionOutcome,
    RecaptionAssets,
    RecaptionReport,
)
from postify.application.media.models import (
    MediaAsset,
    MediaCandidate,
    MediaCounts,
    MediaPage,
)
from postify.application.media.shortlist import MediaShortlist
from postify.application.media.upload import UploadMedia, UploadReport


__all__ = [
    "CaptionMedia",
    "CaptionOutcome",
    "MediaAsset",
    "MediaCandidate",
    "MediaCounts",
    "MediaPage",
    "MediaShortlist",
    "RecaptionAssets",
    "RecaptionReport",
    "UploadMedia",
    "UploadReport",
]
