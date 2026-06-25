import os
import sys
import subprocess
from pathlib import Path

# Prepend node_portable and git_portable\cmd to PATH
base_dir = Path(__file__).parent.resolve()
node_path = base_dir / "node_portable"
git_path = base_dir / "git_portable" / "cmd"

os.environ["PATH"] = f"{node_path};{git_path};" + os.environ.get("PATH", "")

# Run node app.js inside whatsapp_bot
bot_dir = base_dir / "whatsapp_bot"
print("\n" + "="*70)
print("[Wrapper] Starting WhatsApp Baileys Bot + Web Dashboard...")
print("[Wrapper] Dashboard URL: http://localhost:3000")
print("[Wrapper] Using Portable Node.js and Git binaries")
print("="*70 + "\n")

try:
    # Run command and stream outputs to stdout/stderr
    process = subprocess.Popen(
        ["node", "app.js"],
        cwd=str(bot_dir),
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    process.wait()
except KeyboardInterrupt:
    print("\n[Wrapper] Shutting down WhatsApp Bot...")
    try:
        process.terminate()
    except Exception:
        pass
except Exception as e:
    print(f"[Wrapper Error] Failed to launch Node application: {e}")
