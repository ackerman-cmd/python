from collections.abc import Callable

from school_lab.application.ports import Analyzer
from school_lab.domain.errors import AnalysisFailure


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Analyzer]] = {}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._factories)

    def register(self, name: str, factory: Callable[[], Analyzer]) -> None:
        if not name.strip() or name in self._factories:
            raise AnalysisFailure("Требуется непустое уникальное имя", field="analyzer_id")
        if not callable(factory):
            raise AnalysisFailure("Фабрика должна быть вызываемой", field="factory")
        self._factories[name] = factory

    def create(self, name: str) -> Analyzer:
        try:
            factory = self._factories[name]
        except KeyError as exc:
            raise AnalysisFailure(f"Неизвестный анализатор: {name}", field="analyzer_id") from exc
        try:
            analyzer = factory()
        except Exception as exc:
            raise AnalysisFailure("Не удалось создать анализатор", field="factory") from exc
        try:
            analyzer_id = getattr(analyzer, "analyzer_id", None)
            version = getattr(analyzer, "analyzer_version", None)
            analyze = getattr(analyzer, "analyze", None)
        except Exception as exc:
            raise AnalysisFailure("Не удалось прочитать интерфейс анализатора") from exc
        if analyzer_id != name:
            raise AnalysisFailure("Имя регистрации не совпадает с analyzer_id", field="analyzer_id")
        if not isinstance(version, str) or not version.strip():
            raise AnalysisFailure("Версия анализатора обязательна", field="analyzer_version")
        if not callable(analyze):
            raise AnalysisFailure("Метод analyze отсутствует")
        return analyzer
