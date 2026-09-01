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

**Важно:** `GROK_MODEL` и `GROK_IMAGE_MODEL` — разные API. Image-модель в `GROK_MODEL` ломает chat.

При старте бот запрашивает `GET /v1/models` и использует только доступные модели аккаунта.

## Архитектура

```
vk/main.py          → Long Poll, инициализация
vk/handlers.py      → wizard, генерация, оплата
vk/wizard_flow.py   → шаги мастера (площадь, комнаты, чертежи)
vk/media.py         → загрузка фото/PDF в VK
vk/http_fix.py      → патч vkbottle+pydantic (Python 3.10)

core/planner.py     → layout (Grok + grid fallback)
core/render.py      → план PNG/SVG, PDF, watermark
core/room_render.py → 2 ракурса/комната через Grok Imagine
core/blueprint_*    → загрузка и разбор чертежей
grok_client.py      → xAI chat + image API
storage.py          → users, projects, payments
```

## Pipeline генерации

1. Wizard → `ProjectBrief` (комнаты: спальня, санузел, гостиная…)
2. `build_layout()` — Grok JSON + **merge** с brief (все комнаты обязательны)
3. `layout_to_png()` — SVG план с размерами
4. Для **каждой** комнаты из layout:
   - `describe_room()` — текст от проф. дизайнера (chat)
   - `generate_interior_image()` × 2 ракурса (image)
   - нормализация JPEG → upload в VK
5. PDF (pro/full), watermark на free tier для комнат 2+

## Тарифы

| Tier | Что получает пользователь |
|---|---|
| `free` | План + 1 комната HD, остальные с watermark |
| `full` | Все комнаты HD + PDF |
| `pro` | + 3-й ракурс на комнату |
| `preview` | Только план после trial |

## Grok — промпты

- Chat (`grok-build-0.1`): архитектор / дизайнер интерьеров, русский текст
- Image (`grok-imagine-image`): английский photorealistic prompt с **типом комнаты** (bedroom/bath/living)
- Layout: строго **N комнат** из wizard, без пропусков

Файл промптов: `grok_client.py` → `generate_layout`, `describe_room`, `_interior_prompt`

## VK upload — известные проблемы

- PNG от Grok/cairosvg VK часто отклоняет → конвертация в baseline JPEG
- `core/image_normalize.py` — max 1280px, quality 82
- На каждую попытку — **новый** upload URL (`photos.getMessagesUploadServer`)
- Пауза 1.2с между загрузками

## Частые баги и fixes

| Симптом | Причина | Где смотреть |
|---|---|---|
| Chat 400/404 | Image-модель в GROK_MODEL | `.env`, `normalize_grok_models()` |
| Долгий chat | Fallback по недоступным моделям | `refresh_chat_models()`, приоритет API list |
| Нет спальни на фото | Grok вернул < N комнат или VK upload fail | `core/planner.py` merge, логи `vk.media` |
| План без фото | Пустой `photo` от VK upload | `vk/media.py`, JPEG normalize |
| pydantic crash | vkbottle messages.send | `vk/http_fix.py` |

## Документация

- `docs/ARCHITECTURE.md` — схема компонентов
- `docs/PRODUCT.md` — продукт
- `docs/PRICING.md` — тарифы
- `README.md` — быстрый старт

## Стиль коммитов

Сообщения **на русском**, императив: «Исправить…», «Добавить…».

## Правила для AI-агента

1. Минимальный diff, не трогать несвязанный код
2. Не коммитить без явной просьбы пользователя
3. Не пушить без просьбы
4. После правок Grok/VK — напомнить обновить `.env` на сервере
5. Тестировать: `./vk/run.sh` и прогон wizard с 3 комнатами
