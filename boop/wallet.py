from __future__ import annotations

import json
import os

from solders.keypair import Keypair


def load_keypair(secret: str) -> Keypair:
    """Accepts a base58 secret key, a JSON byte array, or a path to a Solana CLI keypair file."""
    s = secret.strip()
    if os.path.isfile(os.path.expanduser(s)):
        with open(os.path.expanduser(s)) as f:
            return Keypair.from_bytes(bytes(json.load(f)))
    if s.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(s)))
    return Keypair.from_base58_string(s)
