"""Product Front Door 的 process-local exact-session composition handle pool。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from .contracts import ConfiguredRevitCandidate, SessionBinding


@dataclass(frozen=True, slots=True)
class _PoolEntry:
    """只缓存 exact binding identity 与 live composition handle，不持有业务真相副本。"""

    binding_hash: str
    composition: object


class ExactSessionCompositionPool:
    """按 immutable session_ref 复用同一 live runtime composition。"""

    def __init__(self, *, factory: Callable[..., object]) -> None:
        """接收显式 composition factory；构造 pool 时不创建任何 runtime。"""

        if not callable(factory):
            raise TypeError("factory must be callable")
        self._factory = factory
        self._entries: dict[str, _PoolEntry] = {}
        # 同一进程内把 lookup/factory/insert 作为一个 single-flight 临界区，避免并发首次
        # submit 为同一 immutable session 创建两套 process-local SnapshotRegistry。
        self._lock = Lock()

    def get_or_create(
        self,
        *,
        binding: SessionBinding,
        candidate: ConfiguredRevitCandidate,
    ) -> object:
        """只按 exact session 查找；同 ref 的不同 binding body 必须 fail closed。"""

        if not isinstance(binding, SessionBinding):
            raise TypeError("binding must be SessionBinding")
        if not isinstance(candidate, ConfiguredRevitCandidate):
            raise TypeError("candidate must be ConfiguredRevitCandidate")

        with self._lock:
            entry = self._entries.get(binding.session_ref)
            if entry is not None:
                if entry.binding_hash != binding.binding_hash:
                    raise ValueError(
                        "FRONT_DOOR_SESSION_BINDING_CONFLICT: session_ref is already bound "
                        "to a different immutable binding"
                    )
                return entry.composition

            composition = self._factory(binding=binding, candidate=candidate)
            if composition is None:
                raise ValueError(
                    "FRONT_DOOR_COMPOSITION_INVALID: factory returned no composition"
                )
            self._entries[binding.session_ref] = _PoolEntry(
                binding_hash=binding.binding_hash,
                composition=composition,
            )
            return composition

    def close(self) -> None:
        """释放本进程缓存的 live handles；重复 close 不重复关闭同一 composition。"""

        with self._lock:
            entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in reversed(entries):
            close = getattr(entry.composition, "close", None)
            if callable(close):
                close()


__all__ = ["ExactSessionCompositionPool"]
