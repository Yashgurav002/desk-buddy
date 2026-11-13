"""Console entry for the packaged build: dbhook.exe hook | dbhook.exe statusline.
Runs hook.py / statusline.py main() unchanged; never fails, always exits 0."""
import os
import sys

if __name__ == "__main__":
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        if mode == "hook":
            import hook as m
        elif mode == "statusline":
            import statusline as m
        else:
            sys.stderr.write("usage: dbhook.exe hook|statusline  (JSON on stdin)\n")
            sys.stderr.flush()
            os._exit(2)
        m.main()
    except BaseException:
        pass
    os._exit(0)
