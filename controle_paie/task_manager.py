from __future__ import annotations

from typing import Callable, Iterable, Optional

from .cancellation import CancellationToken


class TaskManager:
    """Centralise l'etat UI et l'annulation cooperative des traitements SICORPA."""

    def __init__(self, app):
        self.app = app
        self._controls = []
        self._control_states = []
        self._active_operation = ""
        self._cancel_token: CancellationToken | None = None

    @staticmethod
    def _set_control_state(control, state: str) -> None:
        if control is None:
            return
        try:
            control.configure(state=state)
        except Exception:
            pass

    @staticmethod
    def _get_control_state(control) -> str:
        if control is None:
            return "normal"
        try:
            state = str(control.cget("state") or "normal")
            return state
        except Exception:
            pass
        try:
            states = control.state()
            if "disabled" in states:
                return "disabled"
            if "readonly" in states:
                return "readonly"
        except Exception:
            pass
        return "normal"

    @property
    def active_operation(self) -> str:
        return self._active_operation

    @property
    def cancellable(self) -> bool:
        return self._cancel_token is not None and bool(self._active_operation)

    def request_cancel(self) -> bool:
        if self._cancel_token is None:
            return False
        self._cancel_token.cancel()
        return True

    def check_cancelled(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.raise_if_cancelled()

    def _remember_controls(self, controls: Optional[Iterable]) -> None:
        self._controls = [control for control in (controls or []) if control is not None]
        self._control_states = [(control, self._get_control_state(control)) for control in self._controls]
        for control in self._controls:
            self._set_control_state(control, "disabled")

    def restore_controls(self) -> None:
        for control, state in self._control_states:
            self._set_control_state(control, state)
        self._controls = []
        self._control_states = []
        self._active_operation = ""
        self._cancel_token = None

    def run(
        self,
        task: Callable,
        on_success: Callable,
        *,
        operation: str,
        controls: Optional[Iterable] = None,
        loader_title: str = "",
        loader_detail: str = "",
        refresh_data: bool = False,
        cancellable: bool = True,
    ) -> bool:
        self._remember_controls(controls)
        self._active_operation = operation
        self._cancel_token = CancellationToken() if cancellable else None

        if loader_title:
            self.app._open_generation_dialog(
                loader_title,
                loader_detail,
                "Etapes du traitement",
                True,
            )

        def guarded_task():
            self.check_cancelled()
            result = task()
            self.check_cancelled()
            return result

        def success(result):
            try:
                on_success(result)
            finally:
                self.restore_controls()

        started = self.app._background(
            guarded_task,
            success,
            refresh_data=refresh_data,
            operation=operation,
        )
        if not started:
            self.restore_controls()
        return bool(started)

    def handle_failure(self) -> None:
        self.restore_controls()
