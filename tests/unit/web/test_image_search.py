from types import SimpleNamespace
from unittest.mock import Mock

from postify.web import image_search


def test_search_returns_next_five_without_repeating(monkeypatch):
    def query(params):
        offset = params['gsroffset']
        return {'query': {'pages': {str(i): {'pageid': i, 'title': f'File:{i}.jpg', 'index': i,
                  'imageinfo': [{'mime': 'image/jpeg', 'thumburl': f'https://upload.wikimedia.org/{i}.jpg',
                  'descriptionurl': f'https://commons.wikimedia.org/wiki/File:{i}.jpg'}]}
                  for i in range(offset + 1, offset + 6)}}, 'continue': {'gsroffset': offset + 5}}
    monkeypatch.setattr(image_search, '_query', query)
    api = Mock()
    container = SimpleNamespace(api=api)
    first = image_search.search(1, 2, container, q='beach', cursor=0)
    second = image_search.search(1, 2, container, q='beach', cursor=int(first['next_cursor']))
    assert len(first['items']) == len(second['items']) == 5
    assert not {i['id'] for i in first['items']} & {i['id'] for i in second['items']}
    assert api.post.call_count == 2


def test_filters_unsupported_images_and_untrusted_download_hosts():
    data = {'query': {'pages': {'1': {'pageid': 1, 'title': 'File:x', 'imageinfo': [
        {'mime': 'image/jpeg', 'url': 'http://127.0.0.1/private'}]}}}}
    assert image_search._items(data) == []
