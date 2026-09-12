"""Explicitly opted-in live HTTP/AI/Telegram smoke test on the deployed service.

Run inside the application container with AUTOPOST_RELEASE_E2E=1,
AUTOPOST_E2E_CHANNEL_FILE and AUTOPOST_E2E_BASE_URL. Authentication events are
injected locally for a disposable test identity; the operator verifies real login.
Only the test project/account and its own published Telegram message are removed.
"""
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.application.auth.service import AuthService
from postify.config import Settings
from postify.domain.auth.models import TelegramIdentity
from postify.infrastructure.repositories.sqlalchemy_users import SqlAlchemyUserRepository


def main():
    assert os.environ.get('AUTOPOST_RELEASE_E2E') == '1', 'Explicit opt-in required'
    credentials = json.loads(Path(os.environ['AUTOPOST_E2E_CHANNEL_FILE']).read_text())
    base = os.environ['AUTOPOST_E2E_BASE_URL'].rstrip('/')
    output = Path(os.environ.get('AUTOPOST_E2E_REPORT', '/tmp/production-e2e-result.json'))
    report = {'base_url': base, 'started_at': datetime.now(UTC).isoformat()}
    engine = create_engine(str(Settings().database_url))
    auth = AuthService(SqlAlchemyUserRepository(sessionmaker(engine)), bot_username='e2e')
    identity = 'release-e2e-' + uuid4().hex
    project = None
    message_id = None
    with httpx.Client(base_url=base, timeout=90, headers={'Origin': base}) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.is_success, (method, path, response.status_code, response.text[:300])
            return response.json() if response.content else None

        def operation(operation_id):
            deadline = monotonic() + 240
            while monotonic() < deadline:
                result = request('GET', f'/api/projects/{project}/operations/{operation_id}')
                if result['status'] != 'running':
                    assert result['status'] == 'succeeded', result
                    return result
                sleep(.5)
            raise AssertionError('Operation did not finish in 240 seconds')

        try:
            login = request('POST', '/api/auth/login')
            token = login['telegram_url'].split('start=autopost_login_', 1)[1]
            auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity(identity, 'release_e2e', 'Release E2E'))
            auth.handle_bot_decision(telegram_token=token, telegram_user_id=identity, approved=True)
            session = request('GET', '/api/auth/login/status', params={'request': login['browser_token']})
            assert session['status'] == 'approved'
            client.headers['x-postify-csrf'] = session['csrf']
            created = request('POST', '/api/projects', json={'name': 'Release E2E — temporary', 'timezone': 'UTC'})
            project = created['id']
            path = f'/api/projects/{project}'
            request('PUT', path + '/channel', json=credentials)
            assert request('POST', path + '/channel/check')['status'] == 'ok'
            request('PUT', path, json={'publication_mode': 'auto', 'project_prompt':
                'Пиши кратко, по-русски, только по теме слота. Первая строка: Тестовый пост AutoPostTelegram. Без дополнительных фактов.'})
            image = Image.new('RGB', (400, 300), 'white')
            ImageDraw.Draw(image).rectangle((100, 50, 300, 250), fill='green')
            buffer = BytesIO(); image.save(buffer, format='PNG')
            upload = request('POST', path + '/media', files={'files': ('square.png', buffer.getvalue(), 'image/png')})
            operation(upload['operation_id'])
            due = datetime.now(UTC) + timedelta(seconds=120)
            topic = 'Тестовый пост AutoPostTelegram. Зелёный квадрат на белом фоне. Эта тестовая публикация будет удалена после проверки.'
            slot = request('POST', path + '/plan', json={'topic': topic, 'publish_at': due.isoformat()})['id']
            # Планировщик сам забирает слот: ручной generate гоняется с ним.
            deadline = monotonic() + 100
            post = None
            while monotonic() < deadline:
                posts = request('GET', path + '/posts')
                if posts and posts[0]['status'] not in {'generating', 'planned'}:
                    post = request('GET', path + f"/posts/{posts[0]['id']}")
                    break
                sleep(.5)
            assert post is not None, 'Scheduled generation did not finish'
            post_id = post['id']
            report['generated'] = post
            assert post['generation']['provider'] == 'openrouter'
            assert post['validation']['passed'] is True, post['validation']
            assert post['status'] == 'approved', post['status']
            assert 'Тестовый пост AutoPostTelegram' in post['post_text']
            print('Real OpenRouter generation, validation and auto-approval passed', flush=True)
            deadline = monotonic() + 240
            while monotonic() < deadline:
                post = request('GET', path + f'/posts/{post_id}')
                if post['status'] == 'published':
                    break
                sleep(1)
            report['published'] = post
            assert post['status'] == 'published', post
            message_id = post['delivery']['message_id']
            deliveries = request('GET', path + '/publications')
            assert len(deliveries) == 1 and deliveries[0]['attempt_count'] == 1
            report['deliveries'] = deliveries
            report['passed'] = True
            print('Real scheduler published one Telegram message', flush=True)
        finally:
            if project:
                deliveries = request('GET', f'/api/projects/{project}/publications')
                if message_id is None and deliveries:
                    message_id = deliveries[0].get('message_id')
                if message_id:
                    result = httpx.post('https://api.telegram.org/bot' + credentials['bot_token'] + '/deleteMessage',
                        json={'chat_id': credentials['chat_id'], 'message_id': message_id}, timeout=20).json()
                    report['cleanup'] = {'message_id': message_id, 'deleted': result.get('ok') is True}
                    assert result.get('ok') is True, 'Cannot remove the test Telegram message'
                request('DELETE', f'/api/projects/{project}')
            with engine.begin() as connection:
                connection.execute(text('DELETE FROM users WHERE telegram_user_id=:identity'), {'identity': identity})
            report['finished_at'] = datetime.now(UTC).isoformat()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            output.chmod(0o600)
            engine.dispose()
    print('Test project/account removed; report saved', flush=True)


if __name__ == '__main__':
    main()
