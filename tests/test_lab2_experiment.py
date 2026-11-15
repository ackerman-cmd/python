import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/lab2"
EVALUATE = ROOT / "scripts/lab2/evaluate.py"


def test_quality_experiment_reproduces_checked_in_results(tmp_path: Path) -> None:
    output = tmp_path / "quality.json"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(EVALUATE), "--output", str(output)],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    current = json.loads(output.read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "docs/lab2/quality.json").read_text(encoding="utf-8"))
    assert current == expected
    assert current["submissions"] >= 30
    assert current["pairs"] >= 40 and current["template_only_pairs"] >= 5
    assert set(current["families"]["tune"]).isdisjoint(current["families"]["eval"])


def test_quality_experiment_refuses_family_leakage(tmp_path: Path) -> None:
    data = tmp_path / "corpus"
    shutil.copytree(DATA, data)
    path = data / "provenance.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    tune, other = [
        next(row for row in rows if row["split"] == split and not row["parent_id"])
        for split in ("tune", "eval")
    ]
    family = tune["family_id"]
    for row in rows:
        if row["family_id"] == family:
            row["family_id"] = other["family_id"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(EVALUATE), "--data", str(data), "--output", str(output)],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode != 0 and "Family leakage" in result.stderr
    assert not output.exists()


def test_quality_experiment_refuses_identical_code_with_distinct_families(tmp_path: Path) -> None:
    data = tmp_path / "corpus"
    shutil.copytree(DATA, data)
    path = data / "submissions.jsonl"
    rows = {
        row["submission_id"]: row
        for line in path.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))
    }
    source = "tune-template-0-template-only"
    target = "eval-template-0-template-only"
    rows[target]["code"] = rows[source]["code"].replace("\n", "\r\n")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows.values()), encoding="utf-8")
    output = tmp_path / "invalid.json"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(EVALUATE), "--data", str(data), "--output", str(output)],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode != 0 and "Code leakage" in result.stderr
    assert source in result.stderr and target in result.stderr
    assert not output.exists()
