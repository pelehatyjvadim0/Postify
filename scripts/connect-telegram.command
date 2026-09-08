#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose exec app python -m postify.telegram_login
printf '\nНажмите Enter, чтобы закрыть окно.\n'
read -r
