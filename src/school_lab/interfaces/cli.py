import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.sources import JsonlSource
from school_lab.analyzers.similarity import TOKEN_VERSION, token_features
from school_lab.application.similarity import ComparisonService
from school_lab.bootstrap import build_application, load_assignments, load_config
from school_lab.domain.errors import ApplicationError, ConfigurationError
from school_lab.examples.benchmark import benchmark_import
from school_lab.examples.demo import run_demo


def _positive(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Ожидается положительное целое число") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("Ожидается положительное целое число")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backend: приём и анализ работ")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="Импорт JSONL в новый in-memory репозиторий")
    importer.add_argument("path", type=Path)
    importer.add_argument("--config", type=Path)
    demo = commands.add_parser("demo", help="Импорт, повтор, конфликт, анализ и расширение")
    demo.add_argument("--data-dir", type=Path, default=Path("data"))
    benchmark = commands.add_parser("benchmark", help="Измерение импорта учебных записей")
    benchmark.add_argument("--data-dir", type=Path, default=Path("data"))
    benchmark.add_argument("--records", type=_positive, default=1000)
    benchmark.add_argument("--repeats", type=_positive, default=5)
    compare = commands.add_parser("similarity", help="Поиск похожих сдач для ручной проверки")
    compare.add_argument("path", type=Path)
    compare.add_argument("submission_id")
    compare.add_argument("--assignments", type=Path, default=Path("data/assignments.json"))
    compare.add_argument("--config-version", default="1")
    compare.add_argument("--top-k", type=_positive, default=5)
    compare.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args(argv)
    try:
        result: dict[str, object]
        exit_code = 0
        if args.command == "import":
            config = load_config(args.config) if args.config else None
            app = build_application(config)
            summary = import_source(JsonlSource(args.path), app.acceptance_adapter)
            result = summary.to_dict()
            exit_code = 1 if summary.errors else 0
        elif args.command == "demo":
            result = run_demo(args.data_dir)
        elif args.command == "similarity":
            app = build_application()
            summary = import_source(JsonlSource(args.path), app.acceptance_adapter)
            if not args.config_version.strip():
                raise ConfigurationError("Нужна версия конфигурации", field="config_version")
            service = ComparisonService(
                app.repository.all(),
                load_assignments(args.assignments),
                method=TOKEN_VERSION,
                extractor=token_features,
                config_version=args.config_version,
            )
            result = asdict(
                service.top_k(args.submission_id, k=args.top_k, threshold=args.threshold)
            )
            result["import"] = summary.to_dict()
            exit_code = 1 if summary.errors else 0
        else:
            result = benchmark_import(args.data_dir, args.records, args.repeats)
    except ApplicationError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(
            json.dumps(
                {"code": "source_error", "field": "source", "message": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
