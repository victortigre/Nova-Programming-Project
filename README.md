# Nova-Programming-Project
Introduction to programming group project

## Setup (once per computer)

After cloning, turn on the automatic secret check:

```bash
git config core.hooksPath .githooks
```

It runs before every commit and blocks API keys, passwords and secrets files.
The rules are in [AGENTS.md](AGENTS.md). Real keys go in a local `.env` file
(copy `.env.example`), never in the code.
