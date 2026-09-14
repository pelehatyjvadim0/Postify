"""Поиск и импорт изображений Wikimedia Commons без произвольных URL."""
from __future__ import annotations

from html import unescape
import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import Field

from postify.web.auth import owned_project
from postify.web.dependencies import Container
from postify.web.errors import ApiError
from postify.web.schemas.common import RequestSchema

API = 'https://commons.wikimedia.org/w/api.php'
HEADERS = {'User-Agent': 'AutoPostTG/1.0 (image selection; Wikimedia Commons)'}
router = APIRouter(prefix='/api/projects/{project_id}/posts/{post_id}/image-search', dependencies=[Depends(owned_project)])


def _query(params):
    try:
        response = httpx.get(API, params={'action': 'query', 'format': 'json', **params}, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
        if 'error' in data:
            raise ValueError('Commons API error')
        return data
    except (httpx.HTTPError, ValueError) as error:
        raise ApiError(502, 'image_search_unavailable', 'Не удалось найти изображения. Попробуйте ещё раз.') from error


def _plain(value):
    return unescape(re.sub('<[^>]*>', '', value or ''))[:500]


def _items(data):
    result = []
    for page in sorted(data.get('query', {}).get('pages', {}).values(), key=lambda p: p.get('index', 0)):
        info = (page.get('imageinfo') or [{}])[0]
        if info.get('mime') not in {'image/jpeg', 'image/png', 'image/webp'}:
            continue
        url = (info.get('thumburl') or info.get('url', '')).split('?', 1)[0]
        if urlparse(url).scheme != 'https' or urlparse(url).hostname not in {'upload.wikimedia.org', 'thumb.wikimedia.org'}:
            continue
        meta = info.get('extmetadata', {})
        result.append({'id': page['pageid'], 'title': page['title'].removeprefix('File:'),
                       'thumbnail_url': url, 'source_url': info.get('descriptionurl'),
                       'author': _plain(meta.get('Artist', {}).get('value')),
                       'license': _plain(meta.get('LicenseShortName', {}).get('value'))})
    return result


INFO = {'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': 1200}


@router.get('')
def search(project_id: int, post_id: int, container: Container,
           q: str = Query(min_length=1, max_length=200), cursor: int = Query(default=0, ge=0, le=10000)):
    container.api.post(project_id, post_id)
    items = []
    offset = cursor
    # Отбрасываем PDF/SVG и собираем пять растровых изображений, если они есть.
    for _ in range(5):
        data = _query({**INFO, 'generator': 'search', 'gsrsearch': q + ' filetype:bitmap',
                       'gsrnamespace': 6, 'gsrlimit': 5 - len(items), 'gsroffset': offset})
        items.extend(_items(data))
        offset = data.get('continue', {}).get('gsroffset')
        if len(items) == 5 or offset is None:
            break
    return {'items': items, 'next_cursor': offset}


class Selection(RequestSchema):
    id: int = Field(gt=0)


@router.post('/select', status_code=202)
def select(project_id: int, post_id: int, body: Selection, container: Container):
    container.api.post(project_id, post_id)
    items = _items(_query({**INFO, 'pageids': body.id}))
    if not items:
        raise ApiError(400, 'image_unavailable', 'Изображение больше недоступно. Выберите другое.')
    item = items[0]
    limit = container.api.media_upload_limit()
    try:
        with httpx.stream('GET', item['thumbnail_url'], headers=HEADERS, timeout=30, follow_redirects=False) as response:
            response.raise_for_status()
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > limit:
                    raise ApiError(413, 'media_too_large')
    except httpx.HTTPError as error:
        raise ApiError(502, 'image_download_failed', 'Не удалось загрузить картинку. Выберите другую.') from error
    return container.api.upload_media(project_id, [bytes(payload)])
