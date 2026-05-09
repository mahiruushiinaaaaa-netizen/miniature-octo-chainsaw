# AGENTS.md

## Core Rule (Always Follow)
For every task or code change, you MUST:

1. Update the code
2. Review and update documentation
3. Update task tracking

A task is NOT complete until all three are done.

---

## Documentation Rules

### README.md
Update `README.md` if the change affects:
- setup or installation
- usage or commands
- features or functionality
- configuration or environment variables
- project structure
- limitations or notes

Rules:
- Keep it clear and concise
- Do not duplicate sections
- Update existing sections when possible
- dont add unesessary texts
If no README update is needed, explicitly state why.

---

### TASKS.md
Always update `TASKS.md` (create if missing).

Use this format:

#### Done
- what was completed

#### Next
- next steps or suggested improvements

#### Notes
- issues, blockers, or important context

---

## Completion Requirements

Before finishing, always provide:
- files changed
- what behavior changed
- whether README.md was updated (or why not)
- TASKS.md updates
- suggested next step

---

## Behavior Rules
- Do not consider the task complete until code, README, and TASKS are updated
- Prefer small, clear updates over large messy ones
- Keep outputs structured and easy to read

---

## Optional (If Applicable)
- Update `CHANGELOG.md` for major changes
- Suggest improvements or refactoring if helpful