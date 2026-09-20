"""Double-click launcher.

The .pyw extension is the whole trick on Windows: it is associated with
pythonw.exe rather than python.exe, and pythonw runs without allocating a
console, so no black window opens behind the lyrics and none is left behind
when they close. Elsewhere it is an ordinary script.

Nothing is configured here on purpose. Settings live in the config file the app
already writes, and anything passed on the command line still reaches it, so a
shortcut to this file can carry flags the same way.
"""
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE / "mild-lyrics", _HERE, _HERE.parent)
                if str(p) not in sys.path]

if __name__ == "__main__":
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
