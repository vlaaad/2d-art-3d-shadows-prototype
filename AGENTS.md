# Defold prototype

Defold editor HTTP server url:

    http://127.0.0.1:$(cat .internal/editor.port)/openapi.json

## Automation

Use the project-local Automation Bridge client with `PYTHONPATH=automation-bridge-python`. Open the running editor with `editor.open_project(".", start_if_needed=False)`, then use `project.build_and_run()` or `project.connect_engine()` and the typed `game` helpers for scene queries, input, frame/state waits, and screenshots. Prefer semantic annotations/state over coordinates and sleeps; call `game.close_engine()` only when intentionally stopping an engine your script owns.
