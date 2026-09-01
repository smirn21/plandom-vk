# Архитектура

## Компоненты

```
┌─────────────┐     Long Poll      ┌──────────────┐
│  VK API     │ ◄────────────────► │  vk/main.py  │
└─────────────┘                    │  handlers    │
                                   └──────┬───────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
             ┌──────────┐         ┌──────────┐         ┌─────────────┐
             │ storage  │         │ core/    │         │ yookassa    │
             │ projects │         │ planner  │         │ payments    │
             │ payments │         │ render   │         └─────────────┘
             └──────────┘         └────┬─────┘
                                       │
                              ┌────────┴────────┐
                              ▼                 ▼
                        LLM (params)      Image API
                        → ProjectSpec     → room PNG
                        → Layout JSON     → plan SVG→PNG
```

## Доменные модели (`core/models.py`)

- **Project** — квартира или дом, id пользователя, статус draft/done.
- **Room** — name, width_m, length_m, type (bedroom, kitchen, …).
- **LayoutSpec** — JSON для отрисовки плана.
- **GenerationJob** — очередь, тип (plan | furnish | both), cost_tokens.

## Генерация плана (рекомендуемый pipeline)

1. Собрать параметры из wizard → `ProjectBrief`.
2. LLM → строгий JSON (комнаты, связи, approximate sizes).
3. `layout/svg_builder.py` → SVG с подписями.
4. Опционально: LLM/image → текстуры/мебель на рендер по комнатам.
5. Загрузка в VK как `photo` attachment.

## Хранение

SQLite `planirovka.db` (MVP), таблицы:

- `users` — лимиты, subscription, created_at
- `projects` — brief JSON, layout JSON
- `generations` — image paths / vk attachment ids
- `payments` — как в Agrobotik

## Переиспользование из Agrobotik

Копируем и адаптируем (не submodule):

- `yookassa_client.py`
- паттерн `vk/main.py`, `vk/config.py`, `vk/payments.py`
- `storage` payments/subscription helpers

Не копируем: grok plant logic, plants, wiki.

## Деплой

- Python 3.10+, venv `vk/.venv`
- Always-on: `python -m vk.main`
- `.env` отдельный от Agrobotik
