# Nova Marketplace

A second-hand marketplace for Nova SBE students. Students buy and sell the
things that change hands every semester (textbooks, calculators, furniture,
kitchen items, bikes) with other students of the school, and nobody else.

Group project for Introduction to Programming.

**Live app:** https://nova-marketplace.streamlit.app/

## Team

| Name | Student number |
|------|----------------|
| Victor Bethlem Camargo Tigre | 83263 |
| Joana Galhardo Gomes | 56712 |
| Jonathan Mischke | 78340 |
| Maria Beatriz Rodrigues Santos | 80093 |

## Objectives

Students arrive in Lisbon needing a desk, a lamp and a calculator, and leave
a year later needing to get rid of them. Today that happens in WhatsApp groups,
where items are hard to find and you don't know who you are dealing with.

The project set out to build one place for this that is:

1. **Only for Nova SBE.** Every account is a confirmed `@novasbe.pt` email
   address, so buyers and sellers know the other person studies at the school.
2. **Easy to search.** Items have a category, a condition, a price and a pickup
   area, so a buyer can filter and sort instead of scrolling through a chat.
3. **Complete from first message to sale.** A buyer can ask a question, make an
   offer, buy, and both sides can confirm the payment, all in the app.
4. **Safe to use.** Students rate each other after a sale, can report a listing
   or a person, and admins can remove listings and block accounts.
5. **Understandable by the whole team.** It is written in Python with Streamlit
   only, and the rules of the app are covered by automated tests.

## What the app does

- **Accounts and profiles.** Sign up and log in with a Nova SBE email. Each
  student has a profile with a name, program, photo and how they get paid.
- **Selling.** Create a listing with photos, a price (or free), category,
  condition and pickup area. Edit it, mark it reserved or sold, or delete it.
- **Browsing.** Search the listings, filter and sort them, and save favourites.
- **Messages and offers.** Contact a seller in a chat, send a price offer, and
  accept, decline or counter it.
- **Buying.** "Buy Now" reserves the item and shows the buyer how to pay the
  seller: bank transfer or cash in person. The seller confirms when the money
  arrived. The app never moves money itself.
- **Trust and safety.** Star ratings and written feedback after a completed
  sale, house rules every student accepts, reports, and an admin page.

## Try it without installing anything

Open the [live app](https://nova-marketplace.streamlit.app/) and sign up with a
`@novasbe.pt` email address. This is the quickest way to see the project: it
needs no setup, and it is connected to the team's login service and database.

## Installation

You need Python 3.11 or newer and Git.

```bash
git clone https://github.com/victortigre/Nova-Programming-Project.git
cd Nova-Programming-Project

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS and Linux

pip install -r requirements.txt
```

The app uses two outside services: Auth0 for the login and Supabase for the
data and photos. Their keys are secrets, so they are not in this repository.
To run the app on your own computer you need your own:

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
2. Fill in the values. The example file explains where each one comes from.
3. Create the database tables: paste `database_setup.sql` into the Supabase
   SQL Editor and run it.

## Run the application

```bash
streamlit run app.py
```

The app opens at http://localhost:8501.

## Run the tests

```bash
pytest
```

The tests need no secrets and no internet: they use a pretend database that
lives in memory.

## Notes for the team

### Once per computer

After cloning, turn on the automatic secret check:

```bash
git config core.hooksPath .githooks
```

It runs before every commit and blocks API keys, passwords and secrets files.
The rules are in [AGENTS.md](AGENTS.md). Real keys go in a local secrets file,
never in the code.

### Database

`database_setup.sql` is run once for the whole team, and again whenever that
file changes.

Messaging tables and triggers are also defined in `database_setup.sql`. Their
`price_cents` column stores the listing price at first contact as integer cents
(1234 means €12.34), and remains unchanged if the listing is edited or deleted.
The previous standalone Messaging SQL file is no longer used.

If a previous Messaging schema with decimal-euro snapshots or demo listing
references was already applied, setup stops rather than silently changing it.
Ask the database owner to prepare and review a data-preserving upgrade first;
do not drop the tables or rerun an old SQL file. Test setup in a separate
development Supabase project before applying changes to a shared database.

SQL is not executed by the mocked tests. Database privileges, triggers and
concurrent offer retries require separate development-database validation.

### Offers and buying, in detail

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
sold) or "Not received yet". The app never moves money itself. Unconfirmed offer
actions can be retried with the same operation ID.
