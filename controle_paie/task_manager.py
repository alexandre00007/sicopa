from __future__ import annotations

from typing import Callable, Iterable, Optional


class TaskManager:
    """Centralise l'etat UI des traitements asynchrones SICORPA.

    Il s'appuie sur le moteur historique ``_background`` mais garantit que les
    controles enregistres sont restaures apres succes, erreur ou refus de
    lancement parce qu'un autre traitement est deja actif.
    """

    def __init__(self, app):
        self.app = app
        self._controls = []
        self._control_states = []
        self._active_operation = ""

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
    ) -> bool:
        self._remember_controls(controls)
        self._active_operation = operation

        if loader_title:
            self.app._open_generation_dialog(
                loader_title,
                loader_detail,
                "Etapes du traitement",
                True,
            )

        def success(result):
            try:
                on_success(result)
            finally:
                self.restore_controls()

        started = self.app._background(
            task,
            success,
            refresh_data=refresh_data,
            operation=operation,
        )
        if not started:
            self.restore_controls()
        return bool(started)

    def handle_failure(self) -> None:
        self.restore_controls()
