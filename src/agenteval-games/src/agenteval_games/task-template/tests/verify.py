import json
from pathlib import Path
import sys
import urllib.request

# Only the verifier's freshly mounted source is importable, not agent files.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from runtime.verification import verify


def main():
    logs = Path("/logs/verifier")
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.txt").write_text("0\n")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://game:8080/transcript", timeout=30) as response:
        envelope = json.load(response)
    reward = verify(
        envelope,
        Path("/game-public/key.pub").read_bytes(),
        json.loads((HERE / "config.json").read_text()),
        HERE / "data",
    )
    (logs / "transcript.json").write_text(json.dumps(envelope, indent=2) + "\n")
    (logs / "reward.txt").write_text(str(reward) + "\n")


if __name__ == "__main__":
    main()
