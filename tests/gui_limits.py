"""Size limits for the GUI layout tests, aware of the platform's default font.

Qt sizes widgets from the platform's default font. The limits below were tuned on
Windows fonts; the Linux default font is taller, so the same window and the mod
matrix box come out a little taller there (CI measured a 1558 x 913 hint and a
391 px matrix box). The Linux limits keep a margin over that and still catch
runaway layout growth on every platform. The window itself scrolls, so a few
extra pixels of height are harmless in the real app.
"""
import sys

_WINDOWS = sys.platform == "win32"

MAX_HINT_WIDTH = 1700
MAX_HINT_HEIGHT = 900 if _WINDOWS else 1000
MAX_CENTRAL_HEIGHT = 900 if _WINDOWS else 1000
MAX_MATRIX_BOX_HEIGHT = 380 if _WINDOWS else 430
