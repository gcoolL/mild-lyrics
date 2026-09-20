"""Double-click launcher for the TTML synchroniser.

Same trick as mild-lyrics.pyw: .pyw is bound to pythonw on Windows, which
runs without a console, and is an ordinary script everywhere else. Nothing is
configured here -- flags on the command line reach the editor unchanged.
"""
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE / "mild-lyrics", _HERE)
                if str(p) not in sys.path]

if __name__ == "__main__":
    try:
        from editor.app import main
    except SystemExit:
        raise
    except Exception as exc:                      # pragma: no cover
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            app = QApplication(sys.argv)
            QMessageBox.critical(None, "TTML synchroniser",
                                 f"Could not start:\n\n{exc}")
        except Exception:
            pass
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1:]))
