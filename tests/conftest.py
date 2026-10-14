from pathlib import Path

import pytest

from school_lab.bootstrap import Application, build_application
from school_lab.domain.models import AnalysisContext, Assignment
from school_lab.examples.demo import example_payload


@pytest.fixture
def data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def payload(data_dir: Path) -> dict[str, object]:
    return example_payload(data_dir)


@pytest.fixture
def app() -> Application:
    return build_application()


@pytest.fixture
def context() -> AnalysisContext:
    return AnalysisContext(Assignment("assignment-01", "from typing import Iterable\n", ("solve",)))
