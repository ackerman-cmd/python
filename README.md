# ЛР 1 — Приём работ и расширяемые анализаторы

**Backend.** Python 3.12+, Pydantic 2. Итог ЛР 1 доступен по тегу `lab-1`.
Приём неизменяемых версий, строгая валидация, частичный импорт JSONL и заменяемые анализаторы.
Хранилище — в памяти процесса. Принятый код остаётся строкой и не выполняется.

## Структура проекта

```text
lab1/
├── README.md                 # установка, запуск и устройство проекта
├── AI_USAGE.md               # фактическое использование ИИ
├── pyproject.toml            # пакет, зависимости и инструменты проверки
├── requirements-dev.lock     # проверенные версии зависимостей
├── MANIFEST.in               # состав исходного архива
├── src/school_lab/
│   ├── __init__.py
│   ├── __main__.py           # python -m school_lab
│   ├── bootstrap.py          # сборка зависимостей
│   ├── domain/               # модели, ошибки, инварианты, SHA-256
│   ├── application/          # порты, сервисы, реестр, проверка отчёта
│   ├── adapters/             # Pydantic DTO, приём, JSONL и репозиторий
│   ├── analyzers/            # конкретные алгоритмы и расширения
│   ├── interfaces/           # CLI
│   └── examples/             # сквозная демонстрация и измерения
├── tests/                    # unit, контрактные и интеграционные сценарии
├── data/                     # учебный корпус и конфигурация
├── docs/
│   ├── ARCHITECTURE.md       # контракты и архитектурные решения
│   ├── CONTRACTS.md          # схемы данных и Python API
│   ├── REPORT.md             # технический отчёт
│   ├── REVIEW.md             # результаты проверки качества
│   └── evidence/             # результаты тестов, покрытия и демонстрации
└── artifacts/                # локальные сборки и кэши
```

## Установка

Из каталога lab1:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-build-isolation --no-deps -e .
```

На Windows активируют .venv/Scripts/Activate.ps1.
Для установки с разрешением версий вместо lock-файла: `python -m pip install -e '.[dev]'`.

## Запуск

```bash
school-lab demo --data-dir data
school-lab import data/submissions.jsonl --config data/config.json
school-lab import data/invalid_submissions.jsonl
school-lab benchmark --data-dir data --records 1000 --repeats 5
```

Те же аргументы принимает `python -m school_lab`. Python-API расположен в пакетах
school_lab.domain, school_lab.application и school_lab.adapters. Пример расширения:

```python
from school_lab.bootstrap import build_application
from school_lab.analyzers.extensions import DeclarationAnalyzer

app = build_application()
app.registry.register("declaration", DeclarationAnalyzer)
```

Демонстрация выполняет первый и повторный импорт в одном процессе, показывает конфликт,
два анализатора и подключение третьего через прежний сервис. Каждый отдельный запуск import
создаёт новый репозиторий и не видит состояние прошлого процесса.

JSON результата идёт в stdout, диагностика запуска — в stderr. Exit code: 0 — успешный
импорт; 1 — ошибки отдельных записей с сохранением корректных; 2 — ошибка источника,
конфигурации, анализа или аргументов. Ошибки разбора аргументов оформляет argparse;
остальная диагностика запуска имеет JSON-формат. Ожидаемые отрицательные сценарии внутри demo — часть успешной
демонстрации, поэтому её код завершения 0.

## Работа через Python API

Следующий пример использует установленный пакет и данные из каталога `lab1`:

```python
from pathlib import Path

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.sources import JsonlSource
from school_lab.bootstrap import build_application, load_assignments, load_config

data_dir = Path("data")
app = build_application(load_config(data_dir / "config.json"))
assignments = load_assignments(data_dir / "assignments.json")
summary = import_source(JsonlSource(data_dir / "submissions.jsonl"), app.acceptance_adapter)

submission_id = summary.accepted[0]
submission = app.repository.get(submission_id)
assert submission is not None
context = app.context(assignments[submission.assignment_id])
report = app.analysis_service.run(submission_id, "length", context)

repeat = import_source(JsonlSource(data_dir / "submissions.jsonl"), app.acceptance_adapter)
print(len(summary.accepted), len(repeat.duplicate), report.analyzer_id)
```

Для учебного корпуса вывод — `12 12 length`. Репозиторий сохраняется в `app` на всё время
этого сценария. Для приёма одного Python-объекта используется
`app.acceptance_adapter.accept_payload(payload)`, для коллекции — `InMemorySource`.
Их схемы, ошибки и формы результата описаны в [контрактах](docs/CONTRACTS.md).

Команда `import` только принимает работы и выводит сводку. Команда `demo` также запускает
анализ и проверяет расширение. В её JSON важны следующие поля:

| Поле | Что показывает |
|---|---|
| `first_import`, `repeat_import` | Первый приём и точные повторы в одном процессе |
| `mixed_import` | Продолжение после повреждённой строки, конфликта и ошибки схемы |
| `original_preserved` | Сохранность оригинала после конфликта |
| `report_count`, `reports` | 24 отчёта двух основных анализаторов |
| `extension.same_service` | Регистрация третьего анализатора без замены сервиса |

Эталон такого запуска сохранён в [demo.json](docs/evidence/demo.json).
UUID отчётов и время следующего запуска будут отличаться.

## ЛР 2 — поиск похожих сдач

```bash
python -m school_lab similarity data/lab2/submissions.jsonl negative-squares-original --assignments data/lab2/assignments.json --top-k 5 --threshold 0.4166666666666667
python -m school_lab similarity data/lab2/submissions.jsonl negative-squares-original --assignments data/lab2/assignments.json --method ast --threshold 1
python -m school_lab similarity data/lab2/submissions.jsonl negative-squares-original --assignments data/lab2/assignments.json --indexed --threshold 0.4166666666666667
```

Сервис сравнивает сдачи одного задания по Jaccard для множеств токеновых 3-грамм
или признаков AST. Разрешённый шаблон задаётся в `--assignments` и виден отдельно
от совпавшего кода. Выдача содержит балл и исходные диапазоны для обеих работ;
при ошибке компиляции или пустом объединении признаков балл равен `null`.
Код не выполняется. В схеме 2 поле `query` показывает статус исходной
сдачи и диагностику, даже когда кандидатов нет.
Поиск исключает исходную сдачу и отдельно показывает другие версии того же
студента. `--indexed` доступен для токенов и пропускает работы без общей
3-граммы. `review_required` означает ручную проверку; порог по умолчанию 0,5
служит демонстрации, а команды выше используют пороги из эксперимента.

Воспроизведение из корня репозитория:

```bash
python scripts/lab2/make_corpus.py
python scripts/lab2/evaluate.py
python scripts/lab2/benchmark.py --profile
python -m pytest -q --cov=school_lab --cov-branch
```

Синтетический корпус находится в `data/lab2/`. Результаты, команды для защиты
и ограничения — в [отчёте ЛР 2](docs/lab2/REPORT.md).

## Входные файлы и конфигурация

JSONL содержит по одной работе в каждой физической строке; строки кода внутри объекта
записываются как JSON-строки с `\n`. Версия схемы — 1, все ключи обязательны, неизвестные
поля отклоняются. Полный пример входного объекта приведён в
[docs/CONTRACTS.md](docs/CONTRACTS.md).

`data/config.json` задаёт `config_version` и список `length`/`template` с пустыми `params`.
`data/assignments.json` содержит задания с разрешённым шаблоном и требованиями.
Приём и анализ разделены: `import` не требует каталога заданий, а `demo` проверяет наличие
контекста для каждой принятой работы. Изменение любого поля принятой версии требует нового ID.

Воспроизводимость зависит от трёх разных версий: `schema_version` описывает вход,
`analyzer_version` — алгоритм, `config_version` — настройки. Версия пакета `0.1.0`
характеризует поставку приложения и не заменяет эти значения.

## Проверка и сборка

```bash
python -m pytest -q --cov=school_lab --cov-branch --cov-report=term-missing --cov-report=json:docs/evidence/coverage.json --cov-report=html:artifacts/coverage/html --junitxml=docs/evidence/tests.xml
ruff check src tests
ruff format --check src tests
mypy src
python -m build --no-isolation --outdir artifacts/dist
```

Итог: **185 тестов**, **99,88% строк**, **100,00% ветвей**. Суммарная метрика coverage —
99,90%. В конфигурации задан минимальный порог суммарной метрики 90%.
Непокрыт один защитный AssertionError при нарушении контракта conflict в demo.

Кэши pytest, Ruff и mypy настроены на artifacts/cache. База coverage и HTML находятся
в artifacts/coverage. JSON и JUnit, подтверждающие результат, сохраняются в docs/evidence.

Обычная установка wheel проверяется в отдельном временном окружении:

```bash
python3 -m venv artifacts/venvs/release
artifacts/venvs/release/bin/python -m pip install -r requirements-dev.lock
artifacts/venvs/release/bin/python -m pip install --no-deps artifacts/dist/school_lab-0.1.0-py3-none-any.whl
artifacts/venvs/release/bin/python -I -m school_lab demo --data-dir data
```

На Windows замените bin/python на Scripts/python.exe. Ключ -I исключает случайный импорт
из текущего каталога. Wheel содержит код; каталог data передаётся как внешние учебные данные
и входит в исходный архив.

## Архитектурные границы

Контракты, жизненные циклы и обоснование решений описаны в
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Пакет | Ответственность |
|---|---|
| domain | Неизменяемые модели, чистые инварианты, ошибки и стабильные отпечатки |
| application | Контракты портов, приём доменной сдачи, анализ через реестр и проверка результата |
| adapters | Внешняя схема Pydantic, DTO → домен, источники, импортёр, in-memory хранилище |
| analyzers | LengthAnalyzer, TemplateAnalyzer и подключаемые расширения |
| interfaces | Аргументы CLI, сериализация ответа и код завершения |
| examples | Воспроизводимый сквозной сценарий и измерение импорта |

Domain не импортирует Pydantic, HTTP или адаптеры. Application зависит от domain и собственных
портов; конкретные источники и анализаторы подключает bootstrap. Репозиторий и реестр
отдельны для каждой сборки. Глобальное изменяемое состояние не служит контейнером зависимостей.

## Контракты обработки

- Все поля Submission обязательны. Версия — строгий integer 1; время — ISO 8601 с зоной;
  идентификаторы непустые; хотя бы одно из text/code непустое. При used=true обязательны
  непустые tool и purpose. Nullable-поле отличается от отсутствующего.
- DTO строгий, запрещает лишние поля, включая вложенную декларацию. Домен защищает те же
  инварианты при прямом создании. Вход не меняется, исходные пробелы и переводы строк сохраняются.
- SHA-256 вычисляется от всей сдачи: UTF-8 JSON, sort_keys=True, ensure_ascii=False,
  separators=(",", ":"), allow_nan=False. Порядок ключей не влияет, исходное представление
  даты и переводы строк влияют. Это политика данного Python-проекта.
- Новый ID — accepted; тот же ID и хеш — duplicate с сохранённым объектом;
  тот же ID и другое содержание — conflict без перезаписи. Ошибка: code, field, message.
- Повреждённый JSON, повторный ключ, NaN/Infinity, пустая физическая строка и превышение
  лимитов парсера — invalid_json с продолжением. JSONL-лимит — 1 000 000 символов, включая
  newline. Нечитаемый файл или неправильная UTF-8-кодировка — ошибка источника.
- Строки должны кодироваться в UTF-8. Суррогаты отклоняются до хеширования, emoji сохраняются.
  Некорректный ключ в диагностике экранируется и не ломает вывод CLI.
- Файл принадлежит JsonlSource.open и закрывается при завершении, break и исключении.
  InMemorySource выдаёт копии; дополнительный StreamSource не закрывает чужой поток
  и читает с его текущей позиции.
- LengthAnalyzer считает непустые строки, включая комментарии, с rubric_feedback и score=null.
  TemplateAnalyzer ищет точные непрерывные блоки полных строк без нормализации пробелов;
  пустой шаблон не считается совпадением. Совпадение разрешено и не доказывает плагиат.
- Evidence ссылается на исходные строки от 1 включительно. Отчёт связывается с хешем сдачи,
  ID/версией анализатора и config_hash задания с config_version. UUID и время запуска меняются.
- DeclarationAnalyzer описывает принятую декларацию и направляет на ручную проверку,
  если студент не подтвердил проверку результата. MissingExplanationAnalyzer отмечает код
  без текстового пояснения. Ни один анализатор не определяет авторство автоматически.
- При сборке проверяются конфигурация, неизвестные/повторные имена и параметры анализаторов.
  Конкретные length/template пока не принимают params: непустые значения отклоняются.

## Документация и данные

- [Архитектура](docs/ARCHITECTURE.md): границы пакетов, контракты, ресурсы и ошибки.
- [Контракты](docs/CONTRACTS.md): поля, Python API, настройки и интерпретация результатов.
- [Технический отчёт](docs/REPORT.md): реализация, результаты сценариев и измерения.
- [Проверка качества](docs/REVIEW.md): покрытие, типизация, архитектура и отрицательные сценарии.
- [Использование ИИ](AI_USAGE.md): применённый инструмент и назначение его использования.

В data/submissions.jsonl находятся 12 учебных записей из корпуса лекции.
В data/invalid_submissions.jsonl — смешанный сценарий с повреждённым JSON, дубликатом,
конфликтом и ошибкой схемы. Задание и конфигурация — data/assignments.json и data/config.json.
Результаты запусков хранятся в docs/evidence, локальные сборки и кэши — в artifacts.

Назначение каждого файла результатов описано в [docs/evidence/README.md](docs/evidence/README.md).
Для знакомства с поведением достаточно `demo`; для объяснения решений — технического
отчёта; для добавления компонента — архитектуры и справочника контрактов.

## Ограничения

Репозиторий хранит состояние одного процесса; последовательные запуски CLI не образуют
постоянную базу. Импорт не откатывает ранее принятые записи при последующей ошибке источника.
Лимит JSONL ограничивает одну строку, а не суммарную память репозитория.

Анализаторы работают с доверенным кодом расширения внутри процесса. Проверка отчёта
защищает контракт результата, но не изолирует плагин. Наблюдения о длине и точных блоках
шаблона не являются оценкой правильности работы. В приложении отсутствуют сетевые вызовы
ИИ и выполнение принятого исходника. Подробные границы выводов приведены в отчёте.
