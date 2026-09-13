# Project instructions

- For Codex development, use only gpt-6-astra: high reasoning for design/planning, medium for implementation/tests. Match the runtime settings; do not silently substitute another model.
- Use PLAN.md for scope and README.md for setup and verified commands.
- Keep public API schemas and events independent of PydanticAI and Temporal types.
- Keep workflow coordination deterministic; execute model and tool I/O through activities.
- Make run submission, persisted events, and retried tool effects idempotent or explicitly reconciled.
- Keep credentials out of events and traces; execute untrusted code only in isolated sandboxes.
- Use fake models for default tests. Cover API contracts and recovery paths when changing them.
- Keep roadmap, progress notes, and general coding advice out of this file.
