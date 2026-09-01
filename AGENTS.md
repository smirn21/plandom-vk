# ПланДом VK — руководство для разработки

> **Читай этот файл в начале любой сессии редактирования проекта.**

## Что это

VK-бот **ПланДом** — AI-планировка квартир/домов и фотореалистичный дизайн комнат.

- Репозиторий: `planirovka-vk` (GitHub: `smirn21/plandom-vk`)
- Сервер: `~/planDom`, запуск `./vk/run.sh`
- Python 3.10+, SQLite `planirovka.db`

## Ключевые команды

```bash
./vk/run.sh              # установка deps + запуск бота
python -m vk.main        # то же без run.sh
python scripts/setup_vk_community.py  # оформление сообщества
```

## Переменные окружения (.env)

| Переменная | Назначение |
|---|---|
| `VK_BOT_TOKEN` | Токен сообщества |
| `VK_GROUP_ID` | ID группы |
| `GROK_API_KEY` | xAI API key |
| **`GROK_MODEL`** | **Chat** — планировка, описания (`grok-build-0.1`) |
| **`GROK_IMAGE_MODEL`** | **Image** — интерьеры (`grok-imagine-image`) |
| `YOOKASSA_*` | Оплата тарифов |
| `PLANDOM_VERBOSE=1` | Подробные логи каждого шага (DEBUG для pipeline) |
| `LOG_LEVEL` | Глобальный уровень: INFO (по умолчанию), DEBUG |

**Важно:** `GROK_MODEL` и `GROK_IMAGE_MODEL` — разные API. Image-модель в `GROK_MODEL` ломает chat.

При старте бот запрашивает `GET /v1/models` и использует только доступные модели аккаунта.

## Архитектура

```
vk/main.py          → Long Poll, инициализация
vk/handlers.py      → wizard, генерация, оплата
vk/wizard_flow.py   → шаги мастера (площадь, комнаты, чертежи)
vk/media.py         → загрузка фото/PDF в VK (photo + doc fallback)
vk/progress.py      → статус генерации, typing, точки
vk/log_setup.py     → configure_logging(), StepLog (пошаговые логи)
vk/http_fix.py      → патч vkbottle+pydantic (Python 3.10)

core/planner.py     → layout (Grok + grid fallback)
core/render.py      → план PNG/SVG, PDF, watermark
core/room_render.py → 2 ракурса/комната через Grok Imagine
core/blueprint_*    → загрузка и разбор чертежей
grok_client.py      → xAI chat + image API
storage.py          → users, projects, payments
```

## Pipeline генерации

1. Wizard → `ProjectBrief` (все комнаты из wizard обязательны)
2. `build_layout()` — Grok JSON + **merge** с brief (`core/planner.py`)
3. `layout_to_png()` — SVG план с размерами
4. Прогресс в чате: `vk/progress.py` (typing + статус с точками)
5. Описания комнат — **параллельно** (`asyncio.gather`)
6. Для **каждой** комнаты:
   - `describe_room()` — дизайн-бриф (chat)
   - **Ракурс 1** — `generate_interior_image()` (image)
   - **Vision lock** — `lock_design_from_image()` фиксирует мебель/цвета
   - **Ракурс 2** — image с `locked_layout` (та же расстановка)
   - JPEG normalize → `upload_image_to_messages()` (photo, иначе doc)
7. PDF с DejaVu-шрифтами (`core/render.py`), upload с retry

## Тарифы

| Tier | Что получает пользователь |
|---|---|
| `free` | План + 1 комната HD (2 ракурса), остальные с watermark (1 ракурс) |
| `full` | Все комнаты HD (2 ракурса) + PDF |
| `pro` | Как full, 2 ракурса на комнату |
| `preview` | Только план после trial |

## Grok — промпты

- Chat (`grok-build-0.1`): архитектор / дизайнер интерьеров, русский текст
- Image (`grok-imagine-image`): английский photorealistic prompt с **типом комнаты** (bedroom/bath/living)
- Layout: строго **N комнат** из wizard, без пропусков

Файл промптов: `grok_client.py` → `generate_layout`, `describe_room`, `_interior_prompt`

## VK upload — известные проблемы

- PNG/Grok JPEG VK часто отклоняет → `core/image_normalize.py` (960px, baseline JPEG)
- **`upload_image_to_messages()`** — сначала photo, при пустом `photo` → **doc fallback**
- PDF/doc: 3 попытки, пауза 2с перед PDF, лог `error_descr`
- На каждую попытку — **новый** upload URL
- Пауза между загрузками ~0.8–1.5с

## Логирование

В `.env` для максимальной детализации:

```env
PLANDOM_VERBOSE=1
LOG_LEVEL=DEBUG   # опционально
```

Формат: `время | уровень | модуль | сообщение`

- **`vk/log_setup.py`** — `configure_logging()`, класс **`StepLog`** (`[gen:USER | шаг N | +сек]`)
- **`vk/handlers.py`** — каждый этап генерации: layout, plan, describe, render, upload, PDF
- **`grok_client.py`** — каждый API-запрос с таймингом (chat/image/vision)
- **`vk/media.py`** — каждая попытка upload (photo/doc, retry)
- **`core/planner.py`**, **`core/room_render.py`**, **`vk/progress.py`** — INFO на каждый шаг

При `PLANDOM_VERBOSE=1` httpx/vkbottle приглушены до WARNING.

## Частые баги и fixes

| Симптом | Причина | Где смотреть |
|---|---|---|
| Chat 400/404 | Image-модель в GROK_MODEL | `.env`, `normalize_grok_models()` |
| Фото не доходят | Пустой `photo` от VK | `upload_image_to_messages`, doc fallback |
| PDF не приходит | Ошибка doc upload после многих фото | `vk/media.py`, retry + sleep |
| Ракурсы «разные» | Независимая генерация | `lock_design_from_image()` |
| Кракozябры в PDF | Helvetica без кириллицы | `_register_pdf_fonts()` в render.py |
| pydantic crash | vkbottle messages.send | `vk/http_fix.py` |

## Документация

- `docs/ARCHITECTURE.md` — схема компонентов
- `docs/PRODUCT.md` — продукт
- `docs/PRICING.md` — тарифы
- `README.md` — быстрый старт

## Стиль коммитов

Сообщения **на русском**, императив: «Исправить…», «Добавить…».

## Правила для AI-агента

1. **Читать и обновлять этот файл** при значимых изменениях (pipeline, upload, модели, тарифы)
2. Минимальный diff, не трогать несвязанный код
3. Не коммитить без явной просьбы пользователя
4. Не пушить без просьбы
5. После правок Grok/VK — напомнить обновить `.env` на сервере
6. Тестировать: `./vk/run.sh` и прогон wizard с 3+ комнатами
