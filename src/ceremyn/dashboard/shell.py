"""Assemble the terminal from packaged, independently testable presentation assets."""

from importlib.resources import files

_assets = files("ceremyn.dashboard").joinpath("assets")
_scripts = ("core.js", "views.js", "orders.js", "app.js")
SHELL_HTML = (
    _assets.joinpath("terminal.html")
    .read_text(encoding="utf-8")
    .replace("/* TERMINAL_CSS */", _assets.joinpath("terminal.css").read_text(encoding="utf-8"))
    .replace(
        "/* TERMINAL_JS */",
        "\n".join(_assets.joinpath(name).read_text(encoding="utf-8") for name in _scripts),
    )
)
