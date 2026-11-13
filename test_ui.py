"""T5 checks: selftest renders and exits with RSS < 50 MB; a second instance exits on its own."""
import os
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "desk_buddy.pyw")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


env = dict(os.environ, DESK_BUDDY_HOME=tempfile.mkdtemp(), DESK_BUDDY_PORT=str(free_port()))
env.pop("NOTION_TOKEN", None)

# 1. selftest: renders fake frames, destroys itself, reports RSS
r = subprocess.run([sys.executable, PANEL, "--selftest"], env=env, capture_output=True, text=True, timeout=60)
assert r.returncode == 0, r.stderr
line = [l for l in r.stdout.splitlines() if l.startswith("RSS_MB=")]
assert line, r.stdout + r.stderr
rss = float(line[0].split("=")[1])
print("selftest RSS MB:", rss)
assert rss < 50, rss

# 2. single instance: with the port already held, a normal launch must exit by itself
holder = socket.socket()
holder.bind(("127.0.0.1", int(env["DESK_BUDDY_PORT"])))
p = subprocess.Popen([sys.executable, PANEL], env=env)
try:
    assert p.wait(timeout=15) == 0
finally:
    if p.poll() is None:
        p.kill()  # our own child only
    holder.close()

print("test_ui OK")
