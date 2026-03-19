"""Zero-cost timing primitives for ezchat latency testing.

Usage — context manager:
    with Timer("theme load") as t:
        load_theme("phosphor_green")
    print(t.ms)   # elapsed milliseconds

Usage — decorator:
    @timed("encrypt")
    def encrypt_message(plaintext): ...

Usage — report:
    report = BenchReport("Phase 1 — UI")
    with report.measure("theme load"):
        load_theme("phosphor_green")
    report.print()
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator
from contextlib import contextmanager


# ---------------------------------------------------------------------------
# Core result
# ---------------------------------------------------------------------------
@dataclass
class TimerResult:
    label:      str
    elapsed_ns: int = 0

    @property
    def ms(self) -> float:
        return self.elapsed_ns / 1_000_000

    @property
    def us(self) -> float:
        return self.elapsed_ns / 1_000

    def __str__(self) -> str:
        if self.elapsed_ns < 1_000:
            return f"{self.elapsed_ns} ns"
        if self.elapsed_ns < 1_000_000:
            return f"{self.us:.1f} µs"
        return f"{self.ms:.3f} ms"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------
class Timer:
    """Context manager that records wall-clock elapsed time.

        with Timer("label") as t:
            do_work()
        print(t.ms)
    """

    def __init__(self, label: str = "") -> None:
        self.label      = label
        self.elapsed_ns = 0
        self._start: int = 0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter_ns()
        return self

    def __exit__(self, *_) -> None:
        self.elapsed_ns = time.perf_counter_ns() - self._start

    @property
    def ms(self) -> float:
        return self.elapsed_ns / 1_000_000

    @property
    def us(self) -> float:
        return self.elapsed_ns / 1_000

    @property
    def result(self) -> TimerResult:
        return TimerResult(self.label, self.elapsed_ns)

    def __str__(self) -> str:
        return str(self.result)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------
def timed(label: str = "") -> Callable:
    """Decorator that prints elapsed time after each call.

        @timed("encrypt")
        def encrypt(data): ...
    """
    def decorator(fn: Callable) -> Callable:
        lbl = label or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with Timer(lbl) as t:
                result = fn(*args, **kwargs)
            print(f"  {lbl}: {t}")
            return result

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Multi-measurement report
# ---------------------------------------------------------------------------
@dataclass
class BenchReport:
    title:   str
    results: list[TimerResult] = field(default_factory=list)

    @contextmanager
    def measure(self, label: str) -> Iterator[Timer]:
        """Context manager that records a named measurement into this report."""
        t = Timer(label)
        t.__enter__()
        try:
            yield t
        finally:
            t.__exit__(None, None, None)
            self.results.append(t.result)

    def add(self, result: TimerResult) -> None:
        self.results.append(result)

    def print(self, *, width: int = 48) -> None:
        """Print a formatted timing table to stdout."""
        sep = "─" * width
        print(f"\n  ┌{sep}┐")
        title_pad = f" {self.title} ".center(width)
        print(f"  │{title_pad}│")
        print(f"  ├{'─'*28}┬{'─'*(width-29)}┤")
        for r in self.results:
            label = r.label[:27].ljust(28)
            value = str(r).rjust(width - 29)
            print(f"  │{label}│{value}│")
        print(f"  └{'─'*28}┴{'─'*(width-29)}┘")

    def slowest(self) -> TimerResult | None:
        return max(self.results, key=lambda r: r.elapsed_ns) if self.results else None

    def total_ns(self) -> int:
        return sum(r.elapsed_ns for r in self.results)
