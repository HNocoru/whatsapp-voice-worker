"""Las reglas de import-linter deben ROMPERSE ante una violación (W0: criterio de hecho)."""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINT = [sys.executable, "-c", "from importlinter.cli import lint_imports_command as m; m()"]


def run_lint(project: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(project / "src")}
    return subprocess.run(  # noqa: S603
        LINT, cwd=project, env=env, capture_output=True, text=True, timeout=120, check=False
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """Copia aislada del paquete y su configuración; la violación nunca toca el repo."""
    shutil.copytree(
        ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def test_clean_copy_passes_so_a_failure_is_attributable(sandbox: Path) -> None:
    result = run_lint(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("relative_file", "injected", "contract_fragment"),
    [
        ("call_bridge/domain/call.py", "import httpx", "R1"),
        ("call_bridge/application/ports.py", "import httpx", "R2"),
        ("call_events/application/__init__.py", "import livekit", "R2"),
        ("call_events/__init__.py", "import phonic", "R3"),
        ("health/__init__.py", "import httpx", "R4"),
        ("call_events/__init__.py", "import pt_worker.call_bridge", "R5"),
        ("app_client/__init__.py", "import pt_worker.health", "R5b"),
        ("main.py", "import livekit", "R3"),
        ("main.py", "import httpx", "R4"),
    ],
)
def test_a_deliberate_violation_breaks_lint_imports(
    sandbox: Path, relative_file: str, injected: str, contract_fragment: str
) -> None:
    target = sandbox / "src" / "pt_worker" / relative_file
    target.write_text(target.read_text() + f"\n{injected}\n")
    result = run_lint(sandbox)
    assert result.returncode != 0
    # El contrato concreto debe figurar como BROKEN (no basta con que su nombre aparezca).
    assert re.search(rf"^{contract_fragment}: .*BROKEN", result.stdout, re.MULTILINE), result.stdout


def test_nothing_imports_reference() -> None:
    """`reference/` no está en el grafo de import-linter, así que esta regla se prueba por AST."""
    banned = ("reference", "ai_call_center", "api_caliope")
    offenders: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] in banned]
    assert offenders == []
