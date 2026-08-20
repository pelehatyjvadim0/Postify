# Сценарий работы с UI v1

## Я открываю рабочую панель

Я запускаю `postify ui` и открываю панель активного проекта. На обзоре вижу счётчики материалов и пакетов, автоматические и ручные лимиты, состояние базы и планировщика, а также последние операции. Новый поиск запускается из верхней панели и показывает итог только после завершения фоновой операции.

Проверено: `test_each_screen_renders_its_real_api_fixture`, `test_new_search_waits_for_terminal_run_before_refreshing_dashboard`, `test_overview_and_journal_render_runtime_and_recent_operations`.

## Я работаю с материалами и пакетами

Я перехожу к материалам, отбираю все, выбранные или отклонённые записи и открываю безопасно отображаемые детали. В проверке я открываю пакет, читаю текст, источник, анализ, историю и сведения о медиа, затем одобряю или отклоняю его. При необходимости запускаю подбор ещё трёх пакетов, повтор анализа, возврат в анализ, перегенерацию, замену медиа или публикацию сейчас; панель ждёт конечный результат операции.

Проверено: `test_review_detail_loads_real_detail_history_analysis_and_media`, `test_review_mutations_are_real_and_refresh_packages`, `test_package_background_actions_wait_for_terminal_run_and_refresh_review`, `test_load_more_waits_for_terminal_run_and_renders_new_package_without_reload`.

## Я контролирую доставку и журнал

Я вижу очередь, историю публикаций с попытками доставки и могу повторить доступную отправку. В журнале запускаю ручной поиск или единичную публикацию, наблюдаю состояние и итог фоновой операции, её модель, effort и счётчики. Ошибка операции показывается как ошибка, а не как успешное выполнение.

Проверено: `test_publication_detail_renders_attempt_outcomes_and_external_message_id`, `test_manual_delivery_retry_is_a_project_scoped_owner_command`, `test_publish_once_waits_for_terminal_failure_instead_of_reporting_success`.

## Я настраиваю проект по секциям

Я меняю основную информацию, источники, отбор, генерацию, CTA, каналы и маршруты, расписание и дополнительные параметры по одному разделу. Для каналов могу сохранить, заменить или удалить токен и проверить соединение. Перед запросом панель проверяет обязательные поля, URL, расписание и связи маршрута; ошибки доступны и объясняют, что исправить.

Проверено: `test_settings_save_is_section_scoped_dirty_busy_and_refreshes_summary`, `test_stateful_crud_updates_and_deletes_the_created_route_id`, `test_channel_token_keep_replace_remove_and_real_check_are_distinct_intents`, `test_settings_validate_shares_slots_url_and_route_references_before_request`.

## Я получаю честную обратную связь

На каждом экране есть состояния загрузки, ошибки и пустого списка. Диалоги закрываются после успешной команды, мобильная навигация оставляет все рабочие экраны доступными, а данные API выводятся как текст, не как разметка.

Проверено: `test_loading_error_retry_and_empty_are_explicit`, `test_api_text_is_escaped_instead_of_inserted_as_markup`, `test_mobile_more_menu_keeps_secondary_routes_reachable`.
