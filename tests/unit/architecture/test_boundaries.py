import ast
import subprocess
import sys
from pathlib import Path

# Packages that transitively reach ceremyn.risk or ceremyn.execution (confirmed by
# direct grep during the M12 design review — see the approved design plan §2). `llm/` must
# never import any of these, even through an apparently-safe submodule: import-linter's two
# existing contracts ("LLM cannot import execution", "LLM cannot import risk") already forbid
# these transitively, but this test asserts it directly against the source so a violation is
# caught with a precise file/line, not just a lint-imports failure.
_FORBIDDEN_TOP_LEVEL_IMPORTS = {
    "ceremyn.risk",
    "ceremyn.execution",
    "ceremyn.broker",
    "ceremyn.oms",
    "ceremyn.paper",
    "ceremyn.live",
    "ceremyn.research",
    "ceremyn.backtest",
    "ceremyn.dashboard.backend",
    "ceremyn.dashboard.alerts",
    "ceremyn.dashboard.views",
    "ceremyn.dashboard.api",
    "ceremyn.dashboard.websocket",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_llm_package_never_imports_execution_adjacent_packages() -> None:
    root = Path(__file__).resolve().parents[3]
    llm_dir = root / "src" / "ceremyn" / "llm"
    violations: list[str] = []
    for path in sorted(llm_dir.rglob("*.py")):
        for module in _imported_modules(path):
            if any(
                module == forbidden or module.startswith(forbidden + ".")
                for forbidden in _FORBIDDEN_TOP_LEVEL_IMPORTS
            ):
                violations.append(f"{path.relative_to(root)} imports {module!r}")
    assert not violations, "\n".join(violations)


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
