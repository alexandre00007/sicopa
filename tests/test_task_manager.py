from controle_paie.task_manager import TaskManager


class FakeControl:
    def __init__(self):
        self.state = "normal"

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeApp:
    def __init__(self, mode="success"):
        self.mode = mode
        self.loader_calls = []

    def _open_generation_dialog(self, title, detail, steps, cancellable):
        self.loader_calls.append((title, detail, steps, cancellable))

    def _background(self, task, success, refresh_data=False, operation=""):
        if self.mode == "refused":
            return False
        if self.mode == "success":
            success(task())
            return True
        if self.mode == "error":
            try:
                task()
            except Exception:
                return True
        return True


def test_task_manager_restores_controls_after_success():
    app = FakeApp("success")
    button = FakeControl()
    manager = TaskManager(app)
    result = []

    assert manager.run(lambda: 42, result.append, operation="test", controls=[button])
    assert result == [42]
    assert button.state == "normal"


def test_task_manager_restores_controls_when_start_is_refused():
    app = FakeApp("refused")
    button = FakeControl()
    manager = TaskManager(app)

    assert not manager.run(lambda: 42, lambda value: None, operation="test", controls=[button])
    assert button.state == "normal"


def test_task_manager_restores_controls_on_failure_hook():
    app = FakeApp("error")
    button = FakeControl()
    manager = TaskManager(app)

    assert manager.run(lambda: (_ for _ in ()).throw(ValueError("boom")), lambda value: None,
                       operation="test", controls=[button])
    assert button.state == "disabled"
    manager.handle_failure()
    assert button.state == "normal"
