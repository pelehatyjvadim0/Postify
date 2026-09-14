"""Поиск по тегам Flickr через public feed и импорт через официальный oEmbed."""
from __future__ import annotations

from collections import OrderedDict
from html import unescape
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import Field

from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.errors import ApiError
from postify.web.schemas.common import RequestSchema

API = 'https://www.flickr.com/services/feeds/photos_public.gne'
OEMBED = 'https://www.flickr.com/services/oembed/'
HEADERS = {'User-Agent': 'AutoPostTG/1.0 (image selection)'}
router = APIRouter(prefix='/api/projects/{project_id}/posts/{post_id}/image-search', dependencies=[Depends(owned_project)])
# Feed содержит до 20 снимков. Snapshot сохраняет порядок при «Найти другие».
_snapshots: OrderedDict[tuple[int, int, str], tuple[float, list[dict]]] = OrderedDict()
_lock = Lock()
TTL = 1800


def _query(params, url=API):
    try:
        response = httpx.get(url, params={'format': 'json', **params}, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('Invalid Flickr response')
        return data
    except (httpx.HTTPError, ValueError) as error:
        raise ApiError(502, 'image_search_unavailable', 'Не удалось найти изображения. Попробуйте ещё раз.') from error


def _plain(value):
    return unescape(re.sub('<[^>]*>', '', value or ''))[:500]


def _safe_image(url):
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == 'https' and parsed.hostname == 'live.staticflickr.com'
            and port in (None, 443) and not parsed.username and not parsed.password
            and bool(re.fullmatch(r'/\d+/\d+_[a-zA-Z0-9]+(?:_[a-zA-Z0-9]+)?\.(?:jpg|png|webp)', parsed.path)))


def _items(data):
    result, seen = [], set()
    for item in data.get('items', []):
        source = item.get('link', '')
        match = re.fullmatch(r'https://www\.flickr\.com/photos/[\w@-]+/(\d+)/', source)
        url = item.get('media', {}).get('m', '')
        if not match or not _safe_image(url):
            continue
        image_id = int(match[1])
        if image_id in seen:
            continue
        seen.add(image_id)
        result.append({'id': image_id, 'title': _plain(item.get('title')).strip() or 'Фото Flickr',
                       'thumbnail_url': url, 'source_url': source,
                       'author': _plain(item.get('author')), 'license': 'Права — на странице источника'})
    return result


def _prune():
    for key, (created, _) in list(_snapshots.items()):
        if monotonic() - created > TTL:
            del _snapshots[key]


@router.get('')
def search(project_id: int, post_id: int, container: Container,
           q: str = Query(min_length=1, max_length=200), cursor: int = Query(default=0, ge=0, le=10000)):
    container.api.post(project_id, post_id)
    # Flickr normalizes multi-word tags: "Haad Rin" -> "haadrin".
    tag = ''.join(q.strip().lower().split())
    if not tag or ',' in tag:
        raise ApiError(400, 'invalid_search_query', 'Введите одно место или тег для поиска.')
    key = (project_id, post_id, tag)
    with _lock:
        _prune()
        snapshot = _snapshots.get(key)
    if snapshot is None:
        if cursor:
            raise ApiError(409, 'image_search_expired', 'Результаты устарели. Нажмите «Найти» ещё раз.')
        items = _items(_query({'tags': tag, 'tagmode': 'all', 'nojsoncallback': 1}))
        with _lock:
            _snapshots[key] = (monotonic(), items)
            while len(_snapshots) > 128:
                _snapshots.popitem(last=False)
    else:
        items = snapshot[1]
    offset = cursor + 5
    return {'items': items[cursor:offset], 'next_cursor': offset if offset < len(items) else None}


class Selection(RequestSchema):
    id: int = Field(gt=0)


@router.post('/select', status_code=202)
def select(project_id: int, post_id: int, body: Selection, container: Container):
    container.api.post(project_id, post_id)
    with _lock:
        _prune()
        item = next((item for key, (_, items) in _snapshots.items()
                     if key[:2] == (project_id, post_id) for item in items if item['id'] == body.id), None)
    if item is None:
        raise ApiError(400, 'image_unavailable', 'Изображение больше недоступно. Повторите поиск.')
    info = _query({'url': item['source_url']}, OEMBED)
    url = info.get('url', '')
    if info.get('type') != 'photo' or not _safe_image(url):
        raise ApiError(400, 'image_unavailable', 'Изображение больше недоступно. Выберите другое.')
    limit = container.api.media_upload_limit()
    try:
        with httpx.stream('GET', url, headers=HEADERS, timeout=30, follow_redirects=False) as response:
            response.raise_for_status()
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > limit:
                    raise ApiError(413, 'media_too_large')
    except httpx.HTTPError as error:
        raise ApiError(502, 'image_download_failed', 'Не удалось загрузить картинку. Выберите другую.') from error
    return container.api.upload_media(project_id, [bytes(payload)])
