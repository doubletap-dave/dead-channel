# Dead Channel

A Cold War-style AI simulation about distrust, deception, incomplete information, and escalation.

Two AI-controlled rival states — the **Northstar Republic** and the **Vesper Union** — run 30–50 turns under conditions of uncertainty. Neither side sees the truth. They see estimates, probabilities, rumors, stale satellite reads, intercepted chatter, and the occasional lie planted by the enemy. Intelligent actors make high-stakes decisions on incomplete, noisy, delayed, manipulated, or false information — and rationally drift toward disaster.

**Optimization target:** uncertainty + personality + memory + deception + consequences = stories we didn't write.

## How it works

- **Mechanical intelligence pipeline.** Every report is a deterministic transform of true world state plus seeded noise, source reliability, and staleness. Enemy deception actions mutate the observation stream itself. An LLM renders the payload into prose — and never sees the truth.
- **Four independent agents per state.** Head of State, Intelligence Chief, Military Chief, Diplomat. Advisors assess in isolation, disagree structurally, and file dissents when overridden.
- **Memory that matters.** Every recommendation makes a falsifiable claim. Claims get scored as truth emerges; advisor trust rises and falls with their track record.
- **Emergent escalation.** No scripted ladder. Perceived threat drives behavior; behavior drives the enemy's perceived threat. DEFCON is a readout of the spiral, not a script.
- **Omniscient observer.** You hold the truth while the states fumble. Watch live, or replay any run turn by turn.

## Status

V0 design approved — see [the design spec](docs/superpowers/specs/2026-08-20-dead-channel-v0-design.md). Implementation incoming.
