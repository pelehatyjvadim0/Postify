#!/usr/bin/env bash

set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly STARTUP_TIMEOUT_SECONDS=120

USE_SUDO=0

log() {
  printf '[AutoPostTG] %s\n' "$*"
}

fail() {
  printf '[AutoPostTG] Ошибка: %s\n' "$*" >&2
  exit 1
}

configure_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return
  fi
  command -v sudo >/dev/null 2>&1 \
    || fail 'установите sudo или запустите скрипт от root.'
  sudo -v
  USE_SUDO=1
}

run_privileged() {
  if [[ "$USE_SUDO" -eq 1 ]]; then
    sudo "$@"
  else
    "$@"
  fi
}

run_docker() {
  run_privileged docker "$@"
}

install_docker_linux() {
  [[ -r /etc/os-release ]] || fail 'не удалось определить дистрибутив Linux.'
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    ubuntu|debian) ;;
    *) fail 'автоматическая установка Docker поддерживает Ubuntu и Debian.' ;;
  esac

  configure_sudo
  log 'Устанавливаю Docker Engine и Docker Compose...'
  run_privileged apt-get update
  run_privileged apt-get install -y ca-certificates curl
  run_privileged install -m 0755 -d /etc/apt/keyrings
  curl --proto '=https' --tlsv1.2 -fsSL "https://download.docker.com/linux/${ID}/gpg" \
    | run_privileged tee /etc/apt/keyrings/docker.asc >/dev/null
  run_privileged chmod a+r /etc/apt/keyrings/docker.asc

  local codename
  codename="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
  printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
    "$ID" "$codename" "$(dpkg --print-architecture)" \
    | run_privileged tee /etc/apt/sources.list.d/docker.sources >/dev/null
  run_privileged apt-get update
  run_privileged apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  run_privileged systemctl enable --now docker
}

prepare_docker_macos() {
  local docker_app='/Applications/Docker.app'

  if ! command -v docker >/dev/null 2>&1 \
    && [[ -x "$docker_app/Contents/Resources/bin/docker" ]]; then
    export PATH="$docker_app/Contents/Resources/bin:$PATH"
  fi
  if ! command -v docker >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      log 'Устанавливаю Docker Desktop...'
      brew install --cask docker
      export PATH="$docker_app/Contents/Resources/bin:$PATH"
    else
      fail 'установите Docker Desktop и повторите запуск.'
    fi
  fi

  if ! docker info >/dev/null 2>&1; then
    [[ -d "$docker_app" ]] || fail 'запустите Docker и повторите установку.'
    log 'Запускаю Docker Desktop...'
    open -a Docker
  fi
}

ensure_docker() {
  case "$(uname -s)" in
    Darwin) prepare_docker_macos ;;
    Linux)
      if ! command -v docker >/dev/null 2>&1 \
        || ! docker compose version >/dev/null 2>&1; then
        install_docker_linux
      elif docker info >/dev/null 2>&1; then
        USE_SUDO=0
      else
        configure_sudo
        if ! run_docker info >/dev/null 2>&1; then
          run_privileged systemctl enable --now docker 2>/dev/null || true
        fi
      fi
      ;;
    *) fail 'поддерживаются macOS, Ubuntu и Debian.' ;;
  esac

  local waited=0
  until run_docker info >/dev/null 2>&1; do
    (( waited >= STARTUP_TIMEOUT_SECONDS )) \
      && fail 'Docker не запустился за 120 секунд.'
    sleep 2
    (( waited += 2 ))
  done
  run_docker compose version >/dev/null 2>&1 \
    || fail 'Docker Compose v2 не найден.'
}

prepare_environment() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
    log 'Создан локальный .env.'
  fi
}

wait_for_app() {
  local attempt
  for attempt in {1..60}; do
    if run_docker compose exec -T app python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000', timeout=2)" \
      >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done
  run_docker compose logs --tail=50 app >&2
  fail 'приложение не стало доступно за 120 секунд.'
}

main() {
  cd "$PROJECT_DIR"
  ensure_docker
  prepare_environment
  log 'Собираю и запускаю приложение...'
  run_docker compose up --build -d app
  wait_for_app
  run_docker compose ps
  log "Готово: $(run_docker compose port app 8000)"
}

main "$@"
