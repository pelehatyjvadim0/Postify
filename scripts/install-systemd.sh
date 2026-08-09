#!/bin/sh
set -eu

die() {
    printf '%s\n' "$1" >&2
    exit 1
}

require_value() {
    name=$1
    value=$2
    [ -n "$value" ] || die "Не задано значение: $name"
    if printf '%s' "$value" | LC_ALL=C grep -q '[[:cntrl:]]'; then
        die "Недопустимый управляющий символ: $name"
    fi
}

require_absolute_path() {
    name=$1
    value=$2
    require_value "$name" "$value"
    case "$value" in
        /*) ;;
        *) die "Путь должен быть абсолютным: $name" ;;
    esac
}

escape_sed() {
    printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

project_dir=
environment_file=
python_path=
service_user=
service_group=
timezone=
destination=
calendar_count=0
calendar_1=
calendar_2=
calendar_3=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --project-dir|--env-file|--python|--user|--group|--timezone|--destination|--on-calendar)
            [ "$#" -ge 2 ] || die "Для $1 необходимо значение"
            option=$1
            value=$2
            shift 2
            ;;
        *)
            die "Неизвестный параметр: $1"
            ;;
    esac

    case "$option" in
        --project-dir) project_dir=$value ;;
        --env-file) environment_file=$value ;;
        --python) python_path=$value ;;
        --user) service_user=$value ;;
        --group) service_group=$value ;;
        --timezone) timezone=$value ;;
        --destination) destination=$value ;;
        --on-calendar)
            calendar_count=$((calendar_count + 1))
            case "$calendar_count" in
                1) calendar_1=$value ;;
                2) calendar_2=$value ;;
                3) calendar_3=$value ;;
                *) die "Нужно указать ровно три значения --on-calendar" ;;
            esac
            ;;
    esac
done

[ "$calendar_count" -eq 3 ] || die "Нужно указать ровно три значения --on-calendar"
require_absolute_path "--project-dir" "$project_dir"
require_absolute_path "--env-file" "$environment_file"
require_absolute_path "--python" "$python_path"
require_absolute_path "--destination" "$destination"
require_value "--user" "$service_user"
require_value "--group" "$service_group"
require_value "--timezone" "$timezone"
require_value "--on-calendar" "$calendar_1"
require_value "--on-calendar" "$calendar_2"
require_value "--on-calendar" "$calendar_3"
case "$calendar_1 $calendar_2 $calendar_3" in
    *'@ON_CALENDAR_1@'*|*'@ON_CALENDAR_2@'*|*'@ON_CALENDAR_3@'*)
        die "В расписании остался шаблонный плейсхолдер"
        ;;
esac
[ -d "$project_dir" ] || die "Каталог проекта не найден: $project_dir"
[ -f "$environment_file" ] || die "Файл окружения не найден: $environment_file"
[ -x "$python_path" ] || die "Python не исполняемый: $python_path"

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
templates_dir="$script_dir/../deploy/systemd"
temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/postify-systemd.XXXXXXXXXX")
backup_dir="$temp_dir/backup"
destination_service="$destination/postify-run-once.service"
destination_timer="$destination/postify-run-once.timer"
installation_started=0
daemon_reload_started=0

cleanup() {
    exit_status=$?
    if [ "$exit_status" -ne 0 ] && [ "$installation_started" -eq 1 ]; then
        for unit in postify-run-once.service postify-run-once.timer postify-publish-once.service postify-publish-once.timer; do
            if [ -e "$backup_dir/$unit" ]; then
                cp "$backup_dir/$unit" "$destination/$unit"
            else
                rm -f "$destination/$unit"
            fi
        done
        if [ "$daemon_reload_started" -eq 1 ]; then
            systemctl daemon-reload || :
        fi
    fi
    rm -rf "$temp_dir"
    exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM

render_template() {
    source_template=$1
    rendered_unit=$2
    sed \
        -e "s|@PROJECT_DIR@|$(escape_sed "$project_dir")|g" \
        -e "s|@ENV_FILE@|$(escape_sed "$environment_file")|g" \
        -e "s|@PYTHON@|$(escape_sed "$python_path")|g" \
        -e "s|@USER@|$(escape_sed "$service_user")|g" \
        -e "s|@GROUP@|$(escape_sed "$service_group")|g" \
        -e "s|@ON_CALENDAR_1@|$(escape_sed "$calendar_1")|g" \
        -e "s|@ON_CALENDAR_2@|$(escape_sed "$calendar_2")|g" \
        -e "s|@ON_CALENDAR_3@|$(escape_sed "$calendar_3")|g" \
        -e "s|@TIMEZONE@|$(escape_sed "$timezone")|g" \
        "$source_template" > "$rendered_unit"
}

render_template "$templates_dir/postify-run-once.service" "$temp_dir/postify-run-once.service"
render_template "$templates_dir/postify-run-once.timer" "$temp_dir/postify-run-once.timer"
render_template "$templates_dir/postify-publish-once.service" "$temp_dir/postify-publish-once.service"
render_template "$templates_dir/postify-publish-once.timer" "$temp_dir/postify-publish-once.timer"

systemd-analyze calendar "$calendar_1"
systemd-analyze calendar "$calendar_2"
systemd-analyze calendar "$calendar_3"
systemd-analyze verify "$temp_dir/postify-run-once.service" "$temp_dir/postify-run-once.timer" "$temp_dir/postify-publish-once.service" "$temp_dir/postify-publish-once.timer"

mkdir -p "$backup_dir"
for unit in postify-run-once.service postify-run-once.timer postify-publish-once.service postify-publish-once.timer; do
    if [ -e "$destination/$unit" ]; then
        cp "$destination/$unit" "$backup_dir/$unit"
    fi
done

installation_started=1
install -D -m 0644 "$temp_dir/postify-run-once.service" "$destination_service"
install -D -m 0644 "$temp_dir/postify-run-once.timer" "$destination_timer"
install -D -m 0644 "$temp_dir/postify-publish-once.service" "$destination/postify-publish-once.service"
install -D -m 0644 "$temp_dir/postify-publish-once.timer" "$destination/postify-publish-once.timer"
daemon_reload_started=1
systemctl daemon-reload
daemon_reload_started=0
installation_started=0
