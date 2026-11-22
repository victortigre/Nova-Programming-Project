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

Messaging tables and triggers are also defined in `database_setup.sql`. Their
`price_cents` column stores the listing price at first contact as integer cents
(1234 means €12.34), and remains unchanged if the listing is edited or deleted.
The previous standalone Messaging SQL file is no longer used.

If a previous Messaging schema with decimal-euro snapshots or demo listing
references was already applied, setup stops rather than silently changing it.
Ask the database owner to prepare and review a data-preserving upgrade first;
do not drop the tables or rerun an old SQL file. Test setup in a separate
development Supabase project before applying changes to a shared database.

Browse offers a Make an Offer form beside Contact Seller. Sending a price and an
optional note opens a structured card in the existing chat. Normal text messages
stay separate; no duplicate message is created for the note. Only the recipient
of the current pending offer can accept, decline or counter it. Counteroffers
preserve the earlier cards and their statuses.

Acceptance records a price agreement. The buyer then taps Buy Now in the chat
(or taps Buy Now on the item page to pay the listed price without an offer):
the item is reserved and the chat shows how to pay the seller: the ways they
accept on My profile (bank transfer with IBAN, and/or cash in person),
shown only to that buyer. The buyer has 48 hours to pay and tap "I've paid"
(cash: when they meet, no deadline), otherwise the purchase is cancelled and the
item is back on sale. The seller checks and taps "Payment received" (the item is
sold) or "Not received yet". The app never moves money itself. Unconfirmed offer actions can be retried with the same operation ID.

SQL is not executed by the mocked tests. Database privileges, triggers and
concurrent offer retries require separate development-database validation.

## Setup (once per computer)

After cloning, turn on the automatic secret check:

```bash
git config core.hooksPath .githooks
```

It runs before every commit and blocks API keys, passwords and secrets files.
The rules are in [AGENTS.md](AGENTS.md). Real keys go in a local `.env` file
(copy `.env.example`), never in the code.
