"""Guards for the package's lazy-import decoupling.

The agent (sandbox) and receiver entrypoints intentionally do NOT share heavy
dependencies. Importing ``app`` must not eagerly pull in ``app.receiver`` (and
its FastAPI/PyGithub stack), otherwise the agent pod would carry web-server
deps it never uses.
"""
import importlib
import sys


def test_importing_app_does_not_import_receiver():
    # Drop any previously-imported app modules so the import is observed fresh.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    importlib.import_module("app")
    assert "app.receiver" not in sys.modules
    assert "app.poller" not in sys.modules


def test_webhook_app_is_lazily_available():
    import app

    # Accessing the attribute triggers the lazy import and yields the FastAPI app.
    assert app.webhook_app is not None
    assert "app.receiver" in sys.modules


def test_unknown_attribute_raises():
    import app

    try:
        app.does_not_exist  # noqa: B018
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected AttributeError for unknown attribute")
