"""Runtime regression: sustained prop collisions must allow immediate retreat.

Run with the editor open:
    PYTHONPATH=automation-bridge-python python3 tools/test_player_collisions.py
The game stays open, with normal input restored, after the checks.
"""
import argparse
import math
import time

from automation_bridge import editor


# Approach the existing authored meshes from both sides. The barrel edge is
# the original reproduction: at scale 0.01 it settles inside and cannot reverse.
CASES = (
    ("barrel edge", -5.5, 2.0, 1, 0),
    ("barrel back", -3.6, 0.2, 0, 1),
    ("tree front", 0, 1.2, 0, -1),
    ("tree back", 0, -2.0, 0, 1),
    ("tree side", -1.6, -0.5, 1, 0),
    ("boulder front", 3.6, 0.2, 0, -1),
    ("fence front", 2.85, 3.6, 0, -1),
)


def drive(game, x, z, seconds):
    game.command("prototype.set_test_drive", {
        "enabled": True, "x": x, "z": z, "seconds": seconds,
    })
    deadline = time.monotonic() + 60
    samples = []
    while True:
        state = game.state("prototype.player").value
        samples.append(state)
        assert all(math.isfinite(state[k]) for k in ("x", "y", "z", "vx", "vz")), state
        assert abs(state["y"]) < 0.001, state
        if not state["test_drive_enabled"]:
            return samples
        assert time.monotonic() < deadline, "test drive did not finish"
        game.wait_frames(1, timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", action="store_true", help="reuse an already rebuilt game")
    parser.add_argument("--case", action="append", help="run only these named cases")
    args = parser.parse_args()
    project = editor.open_project(".", start_if_needed=False)
    game = project.connect_engine() if args.connect else project.build_and_run()
    try:
        for name, x, z, dx, dz in CASES:
            if args.case and name not in args.case:
                continue
            game.command("prototype.set_player_position", {"x": x, "z": z})
            approach = drive(game, dx, dz, 3)
            # These small regions are well inside the barrel and trunk, not
            # substitutes for their collision geometry. Entering either means
            # collision failed even if the player later emerged on another side.
            for state in approach:
                assert not (abs(state["x"] + 3.6) < 0.2 and abs(state["z"] - 1.65) < 0.15), (name, "inside barrel", state)
                assert not (abs(state["x"]) < 0.15 and abs(state["z"] + 0.5) < 0.12), (name, "inside trunk", state)
            stopped = approach[-1]
            escaped = drive(game, -dx, -dz, 1)[-1]
            retreat = (stopped["x"] - escaped["x"]) * dx + (stopped["z"] - escaped["z"]) * dz
            assert retreat > 0.8, (name, "trapped on reverse", retreat, stopped, escaped)
            print(f"PASS {name}: retreated {retreat:.2f} units", flush=True)
        errors = game.logs.tail(20, contains="ERROR:")
        assert not errors, errors
    finally:
        game.command("prototype.set_test_drive", {"enabled": False})
        game.command("prototype.set_player_position", {"x": -2.6, "z": 0.35})


if __name__ == "__main__":
    main()
