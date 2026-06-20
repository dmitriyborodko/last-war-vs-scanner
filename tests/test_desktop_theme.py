import desktop
from desktop import windows_system_color


def test_windows_system_color_converts_windows_bgr_to_rgb(monkeypatch):
    class FakeUser32:
        @staticmethod
        def GetSysColor(index):
            assert index == 13
            return 0x00332211

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.ctypes, "windll", FakeWindll())

    assert windows_system_color(13, "#fallback") == "#112233"


def test_system_color_uses_fallback_outside_windows(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "linux")

    assert windows_system_color(13, "#0067c0") == "#0067c0"
