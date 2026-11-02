"""noita-player: an LLM-driven bot that plays Noita.

Architecture:
  - lua/bot_bridge.lua runs inside the game and streams structured state out
    (UDP, with a file fallback).
  - noita_bot.state_server receives those snapshots.
  - Phase 2 adds a 60 Hz reflex layer + OS-level key injection.
  - Phase 3 adds the LLM strategy brain on top of that.
"""

__version__ = "0.1.0"
