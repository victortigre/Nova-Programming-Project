# Nova Marketplace

A marketplace for the Nova SBE community to buy and sell within the school —
textbooks, furniture, tickets and more. Introduction to Programming group project.

**Live app:** https://nova-marketplace.streamlit.app/

## Team

| Name | Student number |
|------|----------------|
| Victor Bethlem Camargo Tigre | 83263 |
| Joana Galhardo Gomes | 56712 |
| Jonathan Mischke | 78340 |
| Maria Beatriz Rodrigues Santos | 80093 |

## Run the app locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Run the tests:

```bash
pytest
```

The login and the database need a local `.streamlit/secrets.toml` (copy
`.streamlit/secrets.toml.example` and fill in the values). The data is stored in
Supabase; its tables are created by pasting `database_setup.sql` into the Supabase
SQL Editor and running it — once for the whole team, and again whenever that file
changes.

## Setup (once per computer)

After cloning, turn on the automatic secret check:

```bash
git config core.hooksPath .githooks
```

It runs before every commit and blocks API keys, passwords and secrets files.
The rules are in [AGENTS.md](AGENTS.md). Real keys go in a local `.env` file
(copy `.env.example`), never in the code.
