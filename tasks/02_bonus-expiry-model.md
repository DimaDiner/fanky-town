# Модель срока жизни бонусов

## Цель

У транзакции есть дата протухания начисления и тип сторно по истечении срока.

## Контекст

Баланс — поле `customers.balance`; каждое изменение пишется в `transactions`. Срок жизни должен жить на **партии начисления**, а не на кошельке целиком: клиент может потратить часть бонусов раньше срока.

## Требования

1. В `TransactionType` добавить `expiry = "expiry"` — сторно просроченных бонусов.
2. В модель `Transaction` добавить `expires_at = Column(DateTime, nullable=True, index=True)`:
   - для **начислений** (`amount > 0`) — дата/время протухания;
   - для списаний кассы и сторно `expiry` — `NULL`.
3. Safe-migration в `lifespan` `main.py`: `ALTER TABLE transactions ADD COLUMN expires_at DATETIME` (как для колонок `users`).
4. Схемы транзакций (`schemas.py`): поле `expires_at` опционально в ответах списка транзакций, если оно там отдаётся.
5. В админке в подписях типов транзакций добавить: `expiry` → «Истечение срока» (фильтр/таблица, где уже есть `registration` / `birthday` / `manual`).
6. Логика начисления и джоба — **не** в этой задаче.

## Затрагиваемые файлы

- `db/models.py` — enum и колонка
- `main.py` — ALTER TABLE
- `schemas.py` — при необходимости
- `static/admin.html` — `typeLabels` (около строк с `registration` / `birthday` / `manual`)
- `static/client.html` — подпись типа в истории клиента, если есть словарь типов

## Критерии приёмки

- [ ] Колонка `expires_at` появляется на существующей SQLite без ручного SQL
- [ ] Тип `expiry` есть в enum и отображается по-русски в UI транзакций
- [ ] Старые транзакции валидны после ALTER (колонка nullable; разовая простановка срока — задача 04)

## Зависимости

нет

## Примечания

Не включать `native_enum`, который сломает SQLite. Значения enum — строки, как сейчас.

## Результат воркера
- `db/models.py` — добавлен `TransactionType.expiry`, колонка `Transaction.expires_at` (DateTime, nullable, index)
- `main.py` — safe-migration: `ALTER TABLE transactions ADD COLUMN expires_at DATETIME` в lifespan
- `schemas.py` — опциональное поле `expires_at` в `TransactionHistoryItem` и `AdminTransactionItem`
- `static/admin.html` — подпись «Истечение срока» в фильтре и `typeLabels` (таблица и экспорт)
- `static/client.html` — подпись `expiry` в словаре типов истории клиента
- Дата/время выполнения: 2026-08-16 21:33 UTC+5

## Проверка ревьюера
**Статус: ОДОБРЕНО**

Задача выполнена корректно. Добавлены `TransactionType.expiry` и колонка `expires_at` в модель, safe-migration в `lifespan`, поле `expires_at` в `TransactionHistoryItem` и `AdminTransactionItem`, подпись «Истечение срока» в админке (фильтр, таблица, экспорт) и в `client.html`. Миграция на тестовой SQLite проходит без ошибок, старые строки остаются валидными (`expires_at = NULL`). Логика начисления и джоба не затронуты, как требовалось.

Замечание на будущее (не блокирует): в `crud.get_all_transactions_admin` поле `expires_at` пока не пробрасывается в словарь ответа — для текущего этапа это не критично (значения ещё не заполняются), но понадобится при задаче 04.

<!-- СТАТУС: ВЫПОЛНЕНО -->

