# Development plan

Open work. A phase ends with a check a person can run.

## Open items

- A person-operated interface for dsagt whose controls are the same tools the agent holds, derived from tagged routes, with an activity panel showing the agent's work. agent-ui (`~/gitland/agent-ui`) supplies the shell, the primitives, the tool derivation, and the panel; dsagt supplies the routes. Unscheduled. The handlers in `src/dsagt/mcp/*_tools.py` stay free of transport assumptions so they can become those routes.
