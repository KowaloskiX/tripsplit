"""Which suppliers are plugged in: id -> adapter.

The application builds its registry from `Settings.suppliers` (see `build_registry`); the trip
harness builds its own per scenario. Services only ever look a supplier up by the id a booking
carries — nothing branches on a supplier's name.
"""

from collections.abc import Callable, Iterable, Iterator
from datetime import datetime

from app.core.domain.trips import BookingKind, TransportMode
from app.suppliers.ports import SupplierAdapter

type Clock = Callable[[], datetime]


class SupplierRegistry:
    def __init__(self, adapters: Iterable[SupplierAdapter] = ()) -> None:
        self._adapters: dict[str, SupplierAdapter] = {}
        for adapter in adapters:
            if adapter.id in self._adapters:
                raise ValueError(f"supplier {adapter.id!r} is registered twice")
            self._adapters[adapter.id] = adapter

    def get(self, supplier_id: str) -> SupplierAdapter | None:
        return self._adapters.get(supplier_id)

    def __iter__(self) -> Iterator[SupplierAdapter]:
        return iter(self._adapters.values())

    def __len__(self) -> int:
        return len(self._adapters)

    @property
    def ids(self) -> list[str]:
        return list(self._adapters)

    def of_kind(
        self, kind: BookingKind, mode: TransportMode | None = None
    ) -> list[SupplierAdapter]:
        """Every supplier selling `kind` (and, for transport, `mode` when given)."""
        return [
            adapter
            for adapter in self._adapters.values()
            if adapter.capabilities.kind is kind
            and (mode is None or adapter.capabilities.mode is mode)
        ]
