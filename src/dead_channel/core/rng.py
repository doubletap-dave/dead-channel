import hashlib
import random


class SeededRNG:
    """Deterministic RNG factory: each (seed, name, turn, scope) key is an independent substream."""

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def stream(self, name: str, turn: int = 0, **scope: object) -> random.Random:
        key = f"{self.seed}:{name}:{turn}:" + ":".join(f"{k}={v}" for k, v in sorted(scope.items()))
        derived = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
        return random.Random(derived)
