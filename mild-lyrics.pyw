"""Double-click launcher: .pyw runs under pythonw on Windows, so no console
opens. Configures nothing; flags still reach the app."""
import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE / "mild-lyrics", _HERE, _HERE.parent)
                if str(p) not in sys.path]

_OWN_RUN = ("--no-persist", "--snapshot", "--fixture", "--track", "--tray", "--listen")


def _knock() -> bool:
    """A Mild Lyrics hidden in the tray opened instead, before the ~0.2s import
    of lyrics_gui (and the venv hop); main() knocks again for other entries."""
    if (any(a.startswith(_OWN_RUN) for a in sys.argv[1:])
            or os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
        return False
    try:
        import tray
        return tray.knock()
    except Exception:                             # noqa: BLE001 -- no Qt outside the venv
        return False


if __name__ == "__main__":
    if _knock():
        sys.exit(0)
    import usevenv
    usevenv.hop(__file__)
    try:
        from lyrics_gui import main
    except SystemExit:
        raise
    except Exception as exc:                      # pragma: no cover
        # With no console there is nowhere for a traceback to go, and a launcher
        # that fails silently is indistinguishable from one that did nothing.
        # Qt may not even be importable at this point, so this asks for as
        # little as possible.
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Mild Lyrics",
                                 f"Could not start:\n\n{exc}")
        except Exception:
            pass
        raise SystemExit(1)
    main()
