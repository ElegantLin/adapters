"""Verify the sidecar's signed, replayable trajectory, never agent files."""

import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .engine import Session
from .server import canonical


def verify(envelope, public_key, config, data_dir):
    if set(envelope) != {"transcript", "signature"}:
        raise ValueError("Malformed signed envelope")
    transcript = envelope["transcript"]
    signature = base64.b64decode(envelope["signature"], validate=True)
    Ed25519PublicKey.from_public_bytes(public_key).verify(
        signature, canonical(transcript)
    )
    if (
        set(transcript) != {"version", "initial", "turns", "final"}
        or transcript["version"] != 1
    ):
        raise ValueError("Malformed transcript")
    session = Session(config, data_dir)
    if transcript["initial"] != session.public():
        raise ValueError("Initial observation differs from the benchmark")
    turns = transcript["turns"]
    if not isinstance(turns, list) or len(turns) > session.limit:
        raise ValueError("Invalid turn count")
    for turn in turns:
        if set(turn) != {"action", "result"} or not isinstance(turn["action"], str):
            raise ValueError("Malformed turn")
        result = session.step(turn["action"])
        if result != turn["result"]:
            raise ValueError("Observation or reward differs from replay")
    if transcript["final"] != session.public():
        raise ValueError("Final state differs from replay")
    return session.reward
