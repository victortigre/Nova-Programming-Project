# Rules for AI agents (and humans) working in this repository

## Stack

- Python with Streamlit. Do not add another language or web framework.
- Run the app with `streamlit run app.py`, the tests with `pytest`.
  Install packages with `pip install -r requirements.txt`.
- Login goes through Auth0, using Streamlit's built-in `st.login("auth0")`.
  The app never sees or stores a password. Do not build sign-up, password
  or reset forms.
- Only a verified `@novasbe.pt` address may come in. Use `nova_email()` and
  `email_is_verified()` from `accounts.py` for that check, and check it
  where the action happens, not only by hiding a button.

## Secrets

A secret is any API key, password, database connection string, login-provider
client secret, or bot/webhook token. The URL of the deployed app, the names of
the services we use, and example data are not secrets.

1. **Never write a secret in the code**, in a notebook, in a test, in the
   README, or in a commit message. Read it by name instead, for example
   `os.environ["OPENROUTER_API_KEY"]` or `st.secrets["OPENROUTER_API_KEY"]`.
2. **Real values live only in a local secrets file** (`.env` or
   `.streamlit/secrets.toml`) and in the host's settings page. These files are
   listed in `.gitignore` and are never committed.
3. **Every secret gets a placeholder line in `.env.example`**, so teammates
   know it exists. Placeholders only, never real values.
4. **Before creating a secrets file**, confirm it is ignored:
   `git check-ignore -v .env` must print a matching rule. If it prints
   nothing, fix `.gitignore` first.
5. **Before every commit**, the secret check must pass
   (`sh .githooks/check-secrets.sh`). Never skip it with `--no-verify`, and
   never use `git add -f` on an ignored file.
6. **Do not ask a teammate to paste a key into a chat, an issue, or an agent
   conversation**, and do not print secret values in logs or output.
7. **Use keys with the lowest permissions the task needs.**

## If a secret reaches GitHub, even for a moment

Stop and tell the team. Deleting the file or the commit is not enough.

1. Revoke the key in the provider's dashboard and create a new one.
2. Put the new value in the local secrets file and the host's settings.
3. Check the provider's usage page for activity the team did not cause.

## One-time setup on each computer

```bash
git config core.hooksPath .githooks
```

This turns on the automatic secret check before every commit.
