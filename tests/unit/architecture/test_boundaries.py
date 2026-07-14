import subprocess
import sys
from pathlib import Path


def test_import_linter_contracts_hold() -> None:
    root = Path(__file__).resolve().parents[3]
    lint_imports = root / ".venv/bin/lint-imports"
    if not lint_imports.exists():
        lint_imports = Path(sys.executable).resolve().parent / "lint-imports"
    result = subprocess.run(
        [str(lint_imports)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Domain cannot import infrastructure" in result.stdout
    assert "Strategies cannot import execution" in result.stdout
    assert "Strategies cannot import broker" in result.stdout
    assert "LLM cannot import execution" in result.stdout
    assert "LLM cannot import risk" in result.stdout
    assert "Live cannot import broker" in result.stdout
    assert "Live cannot import execution" in result.stdout
    assert "OMS cannot import strategies" in result.stdout
    assert "OMS cannot import paper" in result.stdout
    assert "Risk cannot import broker" in result.stdout
    assert "Risk cannot import execution" in result.stdout
    assert "Risk cannot import strategies" in result.stdout
    assert "Risk cannot import llm" in result.stdout
