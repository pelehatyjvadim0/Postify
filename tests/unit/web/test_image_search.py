from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from postify.web import image_search
from postify.web.errors import ApiError


def feed(count=20):
    return {'items': [{'title': f'Photo {i}', 'link': f'https://www.flickr.com/photos/user/{i}/',
                      'media': {'m': f'https://live.staticflickr.com/65535/{i}_abcdef_m.jpg'},
                      'author': 'Photographer'} for i in range(1, count + 1)]}


@pytest.fixture(autouse=True)
def clear_snapshots():
    image_search._snapshots.clear()
    yield
    image_search._snapshots.clear()


def test_search_returns_four_stable_fives_without_repeating(monkeypatch):
    query = Mock(return_value=feed())
    monkeypatch.setattr(image_search, '_query', query)
    container = SimpleNamespace(api=Mock())
    results = [image_search.search(1, 2, container, q='Haad Rin', cursor=i) for i in (0, 5, 10, 15)]
    assert all(len(result['items']) == 5 for result in results)
    assert len({item['id'] for result in results for item in result['items']}) == 20
    assert results[-1]['next_cursor'] is None
    query.assert_called_once_with({'tags': 'haadrin', 'tagmode': 'all', 'nojsoncallback': 1})


def test_filters_duplicate_images_and_untrusted_hosts():
    data = feed(1)
    data['items'] *= 2
    data['items'] += [{'link': 'https://www.flickr.com/photos/user/2/', 'media': {'m': 'https://127.0.0.1/x.jpg'}}]
    assert len(image_search._items(data)) == 1


def test_expired_pagination_does_not_silently_restart(monkeypatch):
    image_search._snapshots[(1, 2, 'beach')] = (0, [])
    with pytest.raises(ApiError):
        image_search.search(1, 2, SimpleNamespace(api=Mock()), q='beach', cursor=5)


def test_selection_scoped_to_project_and_post(monkeypatch):
    monkeypatch.setattr(image_search, '_query', Mock(return_value=feed()))
    container = SimpleNamespace(api=Mock())
    image_search.search(1, 2, container, q='beach', cursor=0)
    with pytest.raises(ApiError):
        image_search.select(9, 2, image_search.Selection(id=1), container)
    with pytest.raises(ApiError):
        image_search.select(1, 9, image_search.Selection(id=1), container)
    container.api.upload_media.assert_not_called()


def test_select_downloads_verified_oembed_photo(monkeypatch):
    monkeypatch.setattr(image_search, '_query', Mock(return_value=feed(1)))
    container = SimpleNamespace(api=Mock())
    container.api.media_upload_limit.return_value = 100
    image_search.search(1, 2, container, q='beach', cursor=0)
    url = 'https://live.staticflickr.com/65535/1_abcdef_b.jpg'
    query = Mock(return_value={'type': 'photo', 'url': url})
    monkeypatch.setattr(image_search, '_query', query)
    response = httpx.Response(200, content=b'photo bytes', request=httpx.Request('GET', url))
    stream = Mock()
    stream.return_value.__enter__ = Mock(return_value=response)
    stream.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(image_search.httpx, 'stream', stream)
    image_search.select(1, 2, image_search.Selection(id=1), container)
    container.api.upload_media.assert_called_once_with(1, [b'photo bytes'])
    assert stream.call_args.kwargs['follow_redirects'] is False


@pytest.mark.parametrize('url', ['http://127.0.0.1/private', 'https://evil.test/a.jpg', 'https://live.staticflickr.com.evil.test/1/1_a.jpg'])
def test_selection_rejects_untrusted_oembed_url(monkeypatch, url):
    monkeypatch.setattr(image_search, '_query', Mock(return_value=feed(1)))
    container = SimpleNamespace(api=Mock())
    image_search.search(1, 2, container, q='beach', cursor=0)
    monkeypatch.setattr(image_search, '_query', Mock(return_value={'type': 'photo', 'url': url}))
    with pytest.raises(ApiError):
        image_search.select(1, 2, image_search.Selection(id=1), container)
    container.api.upload_media.assert_not_called()


def test_selection_enforces_download_limit(monkeypatch):
    monkeypatch.setattr(image_search, '_query', Mock(return_value=feed(1)))
    container = SimpleNamespace(api=Mock())
    container.api.media_upload_limit.return_value = 3
    image_search.search(1, 2, container, q='beach', cursor=0)
    url = 'https://live.staticflickr.com/65535/1_abcdef_b.jpg'
    monkeypatch.setattr(image_search, '_query', Mock(return_value={'type': 'photo', 'url': url}))
    response = httpx.Response(200, content=b'too large', request=httpx.Request('GET', url))
    stream = Mock()
    stream.return_value.__enter__ = Mock(return_value=response)
    stream.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(image_search.httpx, 'stream', stream)
    with pytest.raises(ApiError):
        image_search.select(1, 2, image_search.Selection(id=1), container)
    container.api.upload_media.assert_not_called()


def test_provider_failure_is_user_facing(monkeypatch):
    monkeypatch.setattr(image_search.httpx, 'get', Mock(side_effect=httpx.ConnectTimeout('timeout')))
    with pytest.raises(ApiError):
        image_search._query({'tags': 'beach'})
