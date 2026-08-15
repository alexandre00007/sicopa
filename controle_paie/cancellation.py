from __future__ import annotations

import threading


class TaskCancelledError(RuntimeError):
    """Interruption demandee par l'utilisateur a un point de progression sur."""


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelledError("Traitement annule par l'utilisateur.")
