from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)


def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted((labels or {}).items()))


def inc(name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    with _lock:
        samples = _histograms[_key(name, labels)]
        samples.append(value)
        if len(samples) > 1000:
            del samples[: len(samples) - 1000]


@contextmanager
def timed(name: str, labels: dict[str, str] | None = None) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        observe(name, (perf_counter() - started) * 1000, labels)


def _labels_text(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    escaped = [f'{key}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for key, value in labels]
    return "{" + ",".join(escaped) + "}"


def prometheus_text() -> str:
    lines: list[str] = []
    with _lock:
        counters = list(_counters.items())
        histograms = [(key, list(values)) for key, values in _histograms.items()]
    for (name, labels), value in sorted(counters):
        lines.append(f"{name}{_labels_text(labels)} {value:g}")
    for (name, labels), values in sorted(histograms):
        if not values:
            continue
        sorted_values = sorted(values)
        total = sum(values)
        count = len(values)
        lines.append(f"{name}_count{_labels_text(labels)} {count}")
        lines.append(f"{name}_sum{_labels_text(labels)} {total:g}")
        for quantile, index in (("0.5", 0.50), ("0.9", 0.90), ("0.99", 0.99)):
            position = min(len(sorted_values) - 1, int(len(sorted_values) * index))
            quantile_labels = tuple(sorted((*labels, ("quantile", quantile))))
            lines.append(f"{name}{_labels_text(quantile_labels)} {sorted_values[position]:g}")
    return "\n".join(lines) + "\n"
