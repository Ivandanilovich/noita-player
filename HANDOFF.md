# Отчет-передатка — проект noita-player (бот для Noita на базе LLM)

_Дата: 2026-11-02 (обновлено). Этот документ самодостаточен: новая сессия должна взять с него старт
без повторного исследования. Детали: `AGENTS.md`, `README.md`, `.agents/current_state.md`,
`.agents/worklog.md` в корне проекта._

## 1. Что это за проект

Бот, играющий в **Noita** с помощью LLM. Архитектура (иерархическое управление):

- **Внутри игры**: Lua-мод `bot_bridge.lua` (установлен в `<game>\mods\noita_player\`)
  каждые ~2 кадра пишет JSON-снимок состояния в `%TEMP%\noita_bot_state.json`.
- **Python-оркестратор** (`noita_bot/`): читает состояние (~50 Гц), Phase 2 добавит слой
  рефлексов (60 Гц, нажатия клавиш через pynput), Phase 3 — LLM-мозг (~0.5 Гц, стратегия:
  цель → действие в виде JSON).
- Состояние текстовое (не пиксели) → работает с любой чат-моделью, провайдер-агностично
  (OpenAI-совместимые эндпоинты, Ollama, LM Studio — на RTX 5090 можно локально).

### Статус фаз
- [x] **Phase 0** — мост состояния: мод → JSON-файл → Python. **ГОТОВО, подтверждено вживую**
  (реальный геймплей: `frame=2032 t=102s player=(256,-79) alive=True via=file:...`).
- [~] **Phase 1** — полный снимок (HP, инвентарь, враги, биом) + живой дашборд.
  **КОД НАПИСАН, ЗАДЕПЛОЕН, ЧАСТИЧНО ПОДТВЕРЖДЁН ВЖИВУЮ** (2026-11-02):
  работает: frame/t/позиция/alive, враги (имя+дист, кап 12), дашборд, smoke-тесты.
  НЕ РАБОТАЕТ: hp/max_hp (игрок и враги — все 5 кандидатов читателей провалились),
  имена предметов (фолбэк `item_<id>`), biome="_EMPTY_". ← ТОЧКА ВХОДА: найти источник HP (задача 1, п.7).
- [ ] Phase 2 — рефлексы + инжект клавиш. **ФУНДАМЕНТ УЖЕ ЕСТЬ**: `tools/send_input.py`
  (клавиши + клики + управление окном, без зависимостей) — им же автономно пройден весь
  путь меню: New Game → выбор режима → Yes → мир → стрим состояния.
- [ ] Phase 3 — LLM-мозг (нужен выбор провайдера: облачный API vs локальная модель).
- [ ] Phase 4 — память посещенных зон, итоги эпизодов.

## 2. Ключевые пути

| Что | Где |
|---|---|
| Игра | `C:\Program Files (x86)\Steam\steamapps\common\noita` (build Jan 25 2025, Lua API v12) |
| Проект | `c:\Users\ivand\Documents\PROJECTS\PETS\noita-player` |
| Данные Noita (сейвы, конфиг) | `C:\Users\ivand\AppData\LocalLow\Nolla_Games_Noita` — **сестра** папок Roaming/Local, НЕ внутри них! |
| Файл состояния | `%TEMP%\noita_bot_state.json` |
| Лог игры (GamePrint, Lua-ошибки; обрезается при каждом запуске) | `<game>\logger.txt` |
| API-доки | `<game>\tools_modding\lua_api_documentation.txt`, `component_documentation.txt` (357 КБ) |
| Luacheck | `tools\luacheck.exe` (в репо) |

## 3. ПРОВЕРЕННЫЕ факты о сборке Noita (НЕ переоткрывать!)

1. **Нет параметра `-lua_script`** (проверено по таблице аргументов бинарника). Кастомный Lua
   работает ТОЛЬКО как мод: `<game>\mods\<имя>\{mod.xml, init.lua}`.
2. **Новые локальные моды регистрируются, но ВЫКЛЮЧЕНЫ** (`enabled="0"` в
   `%USERPROFILE%\AppData\LocalLow\Nolla_Games_Noita\saveNN\mod_config.xml`).
   `launcher.py::enable_mod_in_saves()` сам переключает на `enabled="1"` при каждом запуске
   (создаёт файл, если его нет). Игра перезаписывает эти файлы при выходе — править только
   когда игра закрыта. **Это была причина долгого «нет heartbeats» — уже исправлено.**
3. **Нет LuaSocket** в рантайме игры → транспорт = JSON-файл (UDP-код оставлен как резерв).
4. `mod.xml` должен содержать `request_no_api_restrictions="1"`, чтобы работали `io.*`/`os.*`.
5. Пер-фрейм хуки (доки: `<game>\mods\example\init.lua`): `OnPlayerSpawned(entity)`,
   `OnWorldPostUpdate()` (каждый кадр, только когда мир обновляется — не в меню/паузе).
6. `print()` из мода может НЕ попасть в logger.txt → диагностика через `GamePrint()`
   (маркер `[bot_bridge] ...`).
7. **Нет симуляции клавиш в Lua API** → Phase 2: OS-инжект (pynput) в окно игры. Управление:
   A/D ход, W полет, S присесть/выпить/съесть, ЛКМ использовать предмет, 1-0/колесо слоты,
   F пнуть, E взаимодействие.
8. **Lua 5.1** (без `goto`, без `//`). После правок Lua — обязательно luacheck.
9. `EntityGetComponent` принимает **полные C++ имена классов**: `"HealthComponent"`,
   `"ItemComponent"`, `"VariableStorageComponent"` (по образцу рабочего мода quant.ew).
10. **ItemComponent имеет поле `item_name`** («the name of the item») — имена предметов решено.
11. **HealthComponent НЕ описан** в component_documentation.txt; поля, скорее всего,
    `current_health`/`max_health` (общественная конвенция) — **подтвердить runtime-пробом**.
12. Только ОДИН процесс может слушать порт 54321 (Windows SO_REUSEADDR: дупликат-бинд
    «проходит», но датаграммы идут ПЕРВОМУ). Перед повторными тестами убивать старые
    `python -m noita_bot.launcher`.
13. `data.wak` — кастомный контейнер (не zip); официальный `noita.exe -wizard_unpak` ничего
    не распаковывает. Тупик, не тратить время.
14. `GameGetAllInventoryItems(entity_id) -> {item_ids}`, `EntityGetInRadiusWithTag(x,y,r,tag)`,
    `BiomeMapGetName(x,y)` — подтверждены в API-доках v12.
15. **`EntityGetComponent` валидирует имя типа по реестру**: неверное имя -> ошибка
    `component type X doesn't exist` (логится в logger.txt даже под pcall; игра дедуплицирует
    повторяющиеся ошибки). → Реестр можно зондировать; неверные имена видны в логе.
16. **"HealthComponent" и "health" НЕТ в реестре этой сборки** (проверено ошибкой, 2026-11-02).
    Факты 9-11 выше про HealthComponent устарели — этот пункт их заменяет.
17. **`GamePrint` из мода НЕ попадает в logger.txt** (проверено: ноль `[bot_bridge]` строк при
    работающем моде; логируются только Lua-ошибки). Диагностика теперь — поле `diag` в JSON-
    payload; launcher печатает его одной строкой `[launcher] DIAG: ...`.
18. **VariableStorageComponent: одна переменная на инстанс** (name + value_string/int/bool/float);
    `ComponentGetValue2(comp,"name")` возвращает имя переменной. У игрока на спавне ровно 4
    переменные: ocarina_song, kantele_song, ocarina_song_pos, kantele_song_pos.
    **Переменной "health" У ИГРОКА НЕТ.**
19. Имена врагов через `EntityGetName` = внутренние id (`$animal_zombie`, `$animal_longleg`, ...).
    Инвентарные предметы: `ItemComponent.item_name` пусто, `EntityGetName(item)=""`, VSC у
    предмета нет → имена предметов пока НЕ решены (фолбэк `item_<id>` работает).
20. Меню игры ИГНОРИРУЕТ клавиатуру (Enter ничего не делает — нет подсветки) → управление
    только мышью. Окно Noita 2560x1440, ЦЕНТРИРОВАНО на 3440x1440 (чёрные полосы по бокам).
21. Агентский терминал живёт ВНУТРИ VS Code: выполнение команд может поднимать IDE поверх игры
    → игре нужен TOPMOST: `python tools\send_input.py fix-topmost`. Заголовок окна VS Code
    ЭТОГО проекта содержит "noita" ("...noita-player...") — матчер окон должен совпадать
    ТОЧНО "Noita - Build ..." (этот баг пойман и исправлен в tools/send_input.py).
22. Координаты главного меню (3440x1440, измерены tools/measure_menu.ps1):
    Continue (1718,696), New Game (1718,740), Options (1716,784), Mods (1716,828),
    Release Notes (1716,872), Credits (1716,916), Quit (1716,960); подтверждение New Game
    "Yes" ≈ (1660,728).

## 4. Файлы проекта

```
AGENTS.md                     # гайд для агентов: факты, команды, конвенции (ЧИТАТЬ ПЕРВЫМ)
README.md                     # архитектура + роадмап
config.yaml                   # пути, порт, настройки LLM (используется с Phase 3)
requirements.txt              # pynput, requests, PyYAML
lua/bot_bridge.lua            # ИСТОЧНИК bridge (Lua 5.1!) — копировать в игру только через launcher
lua/mod.xml, lua/compatibility.xml   # метаданные мода (тоже синхронизируются launcher'ом)
noita_bot/launcher.py         # установка+включение мода, запуск игры, listen + вывод
noita_bot/state_server.py     # UDP + file-listener -> GameState dataclass
tests/test_state_server.py    # smoke-тесты транспорта (без игры)
tools/luacheck.exe            # стат. проверка Lua
tools/send_input.py           # клавиши+клики (SendInput) + topmost/окно — ФУНДАМЕНТ Phase 2
tools/measure_menu.ps1        # замер координат текста в скриншоте (калибровка меню)
logs/                         # выходы launcher'а (phase1_test*.log, screenshot*.png)
.agents/current_state.md      # ТОЧНОЕ текущее положение (обновлять на каждом milestone)
.agents/worklog.md            # хронология решений и находок
```

## 5. Команды

```powershell
cd c:\Users\ivand\Documents\PROJECTS\PETS\noita-player

pip install -r requirements.txt
python tests/test_state_server.py                                   # smoke-тесты (без игры)
tools\luacheck.exe --std max -q lua\bot_bridge.lua                  # 0 ошибок; ~25 warnings = Noita-глобалы (норма)

python -m noita_bot.launcher             # установить+включить мод, запустить игру, слушать
python -m noita_bot.launcher --listen-only
```

Живая проверка Phase 0: запуск launcher'а → в игре New Game → строки
`frame=... t=... player=(x,y) alive=True via=file:...`

## 6. ТОЧНОЕ ТЕКУЩЕЕ ПОЛОЖЕНИЕ (2026-11-02, ~12:00)

- Phase 0 работает вживую. Phase 1: **код написан (v2.1), задеплоен, частично работает вживую**.
  Работает: frame/t/px/py/alive, враги (имя+дист, кап 12, тэг "enemy").
  НЕ РАБОТАЕТ: hp/max_hp (игрок и враги), имена предметов (фолбэк item_<id>), biome="_EMPTY_".
- Окружение на момент фиксации (ПОЛЬЗОВАТЕЛЬ ПОПРОСИЛ ЗАМОРОЗИТЬ — не запускать и не исследовать):
  - noita.exe — РАБОТАЕТ, в мире (загружен через Continue), окно topmost;
  - launcher python pid 44140, `--duration 900` (запущен ~11:56, умрёт ~12:12),
    лог logs/phase1_test2.log; после его смерти игра продолжает писать state-файл;
  - state читается напрямую: `Get-Content $env:TEMP\noita_bot_state.json -Raw`.
- Чтобы применить изменения Lua, игру надо ПЕРЕЗАПУСТИТЬ (мод грузится один раз при старте;
  launcher пересинхронизирует lua/bot_bridge.lua при каждом запуске).

## 7. ЗАДАЧИ (по приоритету) — что осталось от Phase 1 и дальше

1. **НАЙТИ ИСТОЧНИК HP** (единственный реальный блокер Phase 1). Все 5 кандидатов
   (VSC.health, VSC-скан по name, HealthBarComponent.current_health/value,
   DamageModelComponent.health) не дали числа; у игрока в VSC переменной "health" НЕТ.
   Ведущие идеи:
   - grep `lua_api_documentation.txt`: ВСЕ функции `Component*` (есть ли перечисление
     полей?) и слово "health" (есть ли GetHealth-хелпер?);
   - системный зонд реестра: все ~150 имён компонентов из component_documentation.txt
     прогнать через EntityGetComponent по игроку (валидные — таблица, невалидные — ошибка),
     затем прощупать поля у тех, что НА игроке; результаты — в payload.diag (механика готова);
   - непробованные кандидаты: CharacterStatsComponent, CharacterDataComponent, HP у
     ДОЧЕРНЕЙ сущности (тело персонажа), переменная "health" может появиться после
     первого урона;
   - web: community Noita-modding wiki — как моды читают HP игрока.
2. Имена предметов: попробовать `EntityGetName` у РОДИТЕЛЯ предмета (API parent/child);
   низкий приоритет — фолбэк `item_<id>` работает, LLM сможет выучить id→имя.
3. biome: почему "_EMPTY_" (сдвинуться/копнуть, или другая Biome* функция API).
4. ground_items: проверить, выбросив/подобрав предмет.
5. **Phase 2** — слой рефлексов поверх tools/send_input.py (базовый ввод уже работает).
6. **Phase 3** — выбор LLM-провайдера (РЕШЕНИЕ ПОЛЬЗОВАТЕЛЯ: облачный API+ключ vs локальный
   Ollama/LM Studio; RTX 5090 32 ГБ хватает на 7-14B, локально $0).
7. **Phase 4** — память посещенных зон, итоги эпизодов.

## 8. Открытые вопросы (обновлено 2026-11-02)

- Источник HP — НЕ РЕШЁНО (задача 1, п.7). "HealthComponent" в реестре нет;
  VariableStorageComponent у игрока есть, но переменной "health" нет (проверено).
- Тэг ground items: «item» vs «pickup» — не проверено (у спавна на земле предметов не было);
  тэг "enemy" РАБОТАЕТ.
- Что возвращает `EntityGetName` для врагов — ОТВЕЧЕНО: внутренние id ($animal_*).
- Phase 3: выбор LLM-провайдера — облачный API + ключ vs локальная Ollama/LM Studio
  (RTX 5090, 32 ГБ — хватит на 7-14B модели, $0 за запуск).

## 9. Конвенции (соблюдать!)

- Никогда не править `<game>\mods\noita_player\` напрямую — источник в `lua/`,
  launcher синхронизирует при каждом запуске.
- `flush=True` у print'ов, которые должны быть видны при редиректе stdout в файл.
- Обновлять `.agents/current_state.md` на каждом значимом шаге; находки и повороты —
  в `.agents/worklog.md`.
- Python: stdlib-first (Phase 0/1 без внешних зависимостей), type hints, dataclasses.
- Luacheck после любых правок Lua.
- **GamePrint НЕ логится в logger.txt** (проверено 2026-11-02) — диагностика идёт через
  `payload.diag` + строку `[launcher] DIAG:`; logger.txt — только Lua-ошибки.
- При управлении меню: игре нужен TOPMOST (`python tools\send_input.py fix-topmost`) —
  агентский терминал живёт в VS Code, который может подниматься поверх игры; матчер окон —
  ТОЧНО "Noita - Build ..." (VS Code проекта noita-player тоже содержит "noita" в заголовке).

## 10. История ключевых поворотов (коротко, подробнее в worklog.md)

1. `-lua_script` не существует в этой сборке (проверено по бинарнику) -> мост работает
   как мод в `mods\noita_player\`.
2. LuaSocket отсутствует (проверено по lua51.dll) -> транспорт через JSON-файл, не UDP.
3. «Нет heartbeats» при живой игре -> мод был зарегистрирован, но `enabled="0"` в
   `save00\mod_config.xml` (новые локальные моды выключены по умолчанию) ->
   `launcher.py::enable_mod_in_saves()` теперь включает мод для всех слотов автоматически.
4. Данные Noita не находились ни в Roaming ни в Local -> они в **AppData\LocalLow**
   (сестра обеих папок).
5. Баг listener'а: `settimeout(0)` + `except OSError: break` убивал поток на первом
   тике (BlockingIOError) -> фикс: малый блокирующий таймаут 0.02 c как такт цикла.
6. Windows SO_REUSEADDR: два процесса могли биндить порт 54321, но датаграммы уходили
   ПЕРВОМУ -> убивать старые launcher'ы перед тестами.
7. GamePrint не попадает в logger.txt (проверено вживую) -> диагностика через payload.diag
   + строку `[launcher] DIAG:` (AGENTS.md/README поправлены).
8. "HealthComponent" нет в реестре компонентов (EntityGetComponent валидирует имена и роняет
   лог-ошибки) -> 5 кандидатов читателей HP, все провалились; HP у игрока — в VSC переменной
   "health" НЕТ -> задача №1 «найти источник HP» (п.7).
9. Клавиатура в меню не работает (Enter игнорируется) -> мышь; tools/send_input.py
   (клавиши+клики+topmost) — автономный прогон меню New Game → мир → стрим ЗАРАБОТАЛ.
10. Матчер окон "noita in title" попадал в VS Code (название проекта noita-player!) ->
    точное совпадение "Noita - Build ..."; игре нужен topmost (терминал агента живёт в IDE).

