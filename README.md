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

## Run the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

The login and the database need a local `.streamlit/secrets.toml` (copy
`.streamlit/secrets.toml.example`). Run the tests with `pytest`.

The data is stored in Supabase. Its tables are created by pasting
`database_setup.sql` into the Supabase SQL Editor and running it. This is
done once for the whole team, and again whenever that file changes.
