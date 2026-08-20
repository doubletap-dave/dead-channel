from dead_channel.core.rng import SeededRNG


def test_substreams_are_deterministic_and_independent():
    a, b = SeededRNG(7), SeededRNG(7)
    sa, sb = a.stream("obs", turn=1), b.stream("obs", turn=1)
    assert [sa.gauss(0, 1) for _ in range(5)] == [sb.gauss(0, 1) for _ in range(5)]
    other = SeededRNG(7).stream("obs", turn=2)
    assert [other.gauss(0, 1) for _ in range(5)] != [sb.gauss(0, 1) for _ in range(5)]


def test_named_streams_independent_same_turn():
    r = SeededRNG(1)
    x = r.stream("obs", turn=1).random()
    y = r.stream("threat", turn=1).random()
    assert x != y


def test_different_seeds_diverge():
    x = SeededRNG(7).stream("obs", turn=1).random()
    y = SeededRNG(8).stream("obs", turn=1).random()
    assert x != y


def test_scope_extends_stream_key():
    a = SeededRNG(3).stream("obs", turn=1, state="northstar")
    b = SeededRNG(3).stream("obs", turn=1, state="vesper")
    assert a.random() != b.random()


def test_scope_order_irrelevant():
    a = SeededRNG(3).stream("obs", turn=1, state="northstar", sector="east")
    b = SeededRNG(3).stream("obs", turn=1, sector="east", state="northstar")
    assert a.random() == b.random()
