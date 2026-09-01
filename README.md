# ПланДом — AI-планировка и обстановка квартир и домов (VK)

Отдельный проект (не Agrobotik): бот ВКонтакте, который по параметрам пользователя
генерирует планировки и визуализации обстановки по комнатам. Оплата через ЮKassa,
как в Agrobotik.

## Статус

**MVP / проектирование.** Каркас репозитория и документация. Код бота — следующий этап
после ответов на вопросы в [docs/PRODUCT.md](docs/PRODUCT.md).

## Быстрый старт (когда будет реализовано)

```bash
cd planirovka-vk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполнить ключи
python -m vk.main
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

## Документация

- [Продукт и сценарии](docs/PRODUCT.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Монетизация](docs/MONETIZATION.md)

## Связь с Agrobotik

Общий паттерн: Long Poll VK, ЮKassa, PythonAnywhere. **Отдельный** репозиторий,
отдельное VK-сообщество, отдельная БД и (рекомендуется) отдельный магазин ЮKassa.
