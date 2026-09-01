# ПланДом — AI-планировка и обстановка квартир и домов (VK)

Отдельный проект (не Agrobotik): бот **ПланДом** в ВКонтакте — планировки и визуализации
по комнатам. Оплата через ЮKassa.

## Статус

**MVP** — рабочий VK-бот: wizard → планировка → PNG комнат → PDF (в платных тарифах), ЮKassa.

## Быстрый старт

```bash
cd planirovka-vk
cp .env.example .env   # VK_BOT_TOKEN, VK_GROUP_ID, GROK_API_KEY, YOOKASSA_*
./vk/run.sh
```

Или вручную:

```bash
python3 -m venv vk/.venv
vk/.venv/bin/pip install -r requirements.txt
vk/.venv/bin/python -m vk.main
```

## Структура

```
planirovka-vk/
├── docs/           PRODUCT, ARCHITECTURE, MONETIZATION
├── vk/             бот VK (vkbottle)
├── core/           доменная логика: комнаты, план, генерация
├── storage.py      SQLite / Postgres
├── yookassa_client.py
└── requirements.txt
```

## Настройка VK-сообщества

```bash
# 1. Положите VK_USER_TOKEN в .env (права: groups, photos, wall)
python3 scripts/generate_vk_assets.py
python3 scripts/setup_vk_community.py
# 2. Выпустите токен бота: ссылка из скрипта → act=tokens → сообщения, фото, docs
# 3. VK_BOT_TOKEN=... в .env, ./vk/run.sh
```

## Документация

- [Продукт и сценарии](docs/PRODUCT.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Тарифы и логика цен](docs/PRICING.md)

## Связь с Agrobotik

Общий паттерн: Long Poll VK, ЮKassa, PythonAnywhere. **Отдельный** репозиторий,
отдельное VK-сообщество, отдельная БД и (рекомендуется) отдельный магазин ЮKassa.
