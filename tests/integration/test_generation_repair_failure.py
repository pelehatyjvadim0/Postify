"""A provider failure must preserve the blocked draft without auto-publishing."""
import json
import pytest
from postify.application.ports.model_provider import ModelCallError
from tests.integration.test_generation_delivery_workflow import workflow, _upload_image, _create_slot, _wait_operation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize('mode', ['review', 'auto'])
def test_repair_outage_preserves_draft_and_blocks_approval(workflow, monkeypatch, mode):
    client, _, _, provider, *_ = workflow
    client.put('/api/projects/1', json={'publication_mode': mode})
    _upload_image(client, provider)
    slot = _create_slot(client)
    original = provider.complete
    def complete(prompt, **kwargs):
        if prompt.startswith('Почини черновик'):
            raise ModelCallError('provider_unavailable', 'temporary upstream failure')
        if 'post_text' in (kwargs.get('output_schema') or {}).get('properties', {}):
            return json.dumps({'post_text': 'Хранение зерна: прибыль выросла на 999%.',
                'media_asset_id': provider.media_asset_id, 'media_rationale': 'Силосы'})
        return original(prompt, **kwargs)
    monkeypatch.setattr(provider, 'complete', complete)
    accepted = client.post(f'/api/projects/1/plan/{slot}/generate')
    op = _wait_operation(client, accepted.json()['operation_id'])
    post_id = op['result']['post_id']
    path = f'/api/projects/1/posts/{post_id}'
    post = client.get(path).json()
    assert post['post_text'] == 'Хранение зерна: прибыль выросла на 999%.'
    assert post['status'] == 'needs_review'
    assert post['validation']['passed'] is False
    assert post['generation']['repair_error'] == 'provider_unavailable'
    assert client.post(path + '/approve').status_code == 409
    assert client.get('/api/projects/1/publications').json() == []
