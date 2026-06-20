import desktop


class FakeWindow:
    def __init__(self):
        self.geometry_value = ""
        self.minimum = ()

    def geometry(self, value):
        self.geometry_value = value

    def minsize(self, width, height):
        self.minimum = (width, height)


def test_window_size_uses_its_current_display_dpi(monkeypatch):
    window = FakeWindow()
    monkeypatch.setattr(desktop, "window_dpi", lambda _window: 144)

    desktop.set_scaled_window_size(window, 1100, 760, 760, 480)

    assert window.geometry_value == "1650x1140"
    assert window.minimum == (1140, 720)
