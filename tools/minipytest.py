"""Minimaler pytest-Ersatz fuer Umgebungen ohne PyPI-Zugriff.

Deckt genau die Features ab, die die PropForge-Suite nutzt: fixtures (inkl.
tmp_path), parametrize, raises, approx. Auf einer normalen Entwicklungsmaschine
sollte stattdessen echtes pytest laufen - dieses Modul existiert nur, damit die
Suite auch in einer abgeschotteten Umgebung ausfuehrbar bleibt.
"""

from __future__ import annotations

import inspect
import sys
import tempfile
import traceback
import types
from pathlib import Path


# --- pytest-kompatible API --------------------------------------------------

class _ApproxScalar:
    def __init__(self, expected, abs_tol=None, rel_tol=None):
        self.expected = expected
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol if rel_tol is not None else (1e-6 if abs_tol is None else None)

    def __eq__(self, actual):
        if self.abs_tol is not None and abs(actual - self.expected) <= self.abs_tol:
            return True
        if self.rel_tol is not None:
            return abs(actual - self.expected) <= self.rel_tol * max(abs(self.expected), 1e-12)
        return False

    def __repr__(self):
        return f"approx({self.expected})"


class _Raises:
    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"Erwartete {self.expected.__name__}, aber nichts wurde geworfen.")
        if not issubclass(exc_type, self.expected):
            return False
        if self.match is not None:
            import re
            if not re.search(self.match, str(exc)):
                raise AssertionError(f"'{self.match}' nicht in '{exc}' gefunden.")
        return True


def fixture(func=None, **_kwargs):
    def wrap(f):
        f.__is_fixture__ = True
        return f
    return wrap(func) if func is not None else wrap


class _Mark:
    @staticmethod
    def parametrize(argnames, argvalues):
        names = [n.strip() for n in argnames.split(",")]

        def decorator(func):
            func.__parametrize__ = (names, list(argvalues))
            return func
        return decorator


def approx(expected, abs=None, rel=None):  # noqa: A002 - pytest-Signatur
    return _ApproxScalar(expected, abs_tol=abs, rel_tol=rel)


def raises(expected, match=None):
    return _Raises(expected, match)


mark = _Mark()


def install() -> None:
    """Registriert dieses Modul unter dem Namen 'pytest'."""
    module = types.ModuleType("pytest")
    module.fixture = fixture
    module.mark = mark
    module.approx = approx
    module.raises = raises
    sys.modules["pytest"] = module


# --- Runner -----------------------------------------------------------------

class Result:
    def __init__(self):
        self.passed = 0
        self.failures: list[tuple[str, str]] = []


def _resolve_args(func, fixtures: dict, tmp_root: Path, cache: dict):
    kwargs = {}
    for param in inspect.signature(func).parameters:
        if param == "self":
            continue
        if param == "tmp_path":
            d = Path(tempfile.mkdtemp(dir=tmp_root))
            kwargs["tmp_path"] = d
        elif param in fixtures:
            if param not in cache:
                fx = fixtures[param]
                cache[param] = fx(**_resolve_args(fx, fixtures, tmp_root, cache))
            kwargs[param] = cache[param]
    return kwargs


def _run_case(label, func, instance, fixtures, tmp_root, result: Result, params=None):
    cache: dict = {}
    try:
        kwargs = _resolve_args(func, fixtures, tmp_root, cache)
        if params:
            kwargs.update(params)
        func(instance, **kwargs) if instance is not None else func(**kwargs)
        result.passed += 1
    except Exception:  # noqa: BLE001
        result.failures.append((label, traceback.format_exc()))


def run_module(module, result: Result, tmp_root: Path) -> None:
    fixtures = {
        name: obj
        for name, obj in vars(module).items()
        if callable(obj) and getattr(obj, "__is_fixture__", False)
    }

    def collect(container, prefix, instance):
        for name, obj in vars(container).items():
            if not name.startswith("test_") or not callable(obj):
                continue
            label = f"{prefix}::{name}"
            if hasattr(obj, "__parametrize__"):
                names, values = obj.__parametrize__
                for vals in values:
                    vals = vals if isinstance(vals, tuple) else (vals,)
                    params = dict(zip(names, vals))
                    _run_case(f"{label}{list(vals)}", obj, instance, fixtures, tmp_root, result, params)
            else:
                _run_case(label, obj, instance, fixtures, tmp_root, result)

    collect(module, module.__name__, None)
    for cname, cls in vars(module).items():
        if isinstance(cls, type) and cname.startswith("Test"):
            collect(cls, f"{module.__name__}.{cname}", cls())


def main(paths: list[str]) -> int:
    install()
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))

    result = Result()
    tmp_root = Path(tempfile.mkdtemp(prefix="minipytest_"))

    import importlib.util
    for path in paths:
        p = Path(path)
        spec = importlib.util.spec_from_file_location(p.stem, p)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        run_module(module, result, tmp_root)

    for label, tb in result.failures:
        print(f"\nFAIL {label}\n{tb}")

    total = result.passed + len(result.failures)
    print(f"\n{result.passed}/{total} Tests bestanden.")
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
