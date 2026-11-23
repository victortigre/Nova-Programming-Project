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

## How it is built

### The parts

| Part | Files | What it does |
|------|-------|--------------|
| Pages | `app.py`, `views/` | What the student sees. `app.py` checks the login and builds the menu; each page in `views/` is one screen. |
| Rules | `listings.py`, `deals.py`, `payments.py`, `offers.py`, `reviews.py`, `reports.py`, `admin.py`, `browsing.py`, `photos.py`, `accounts.py` | Plain Python that decides what is allowed: who may edit a listing, when a deal is cancelled, what a valid IBAN looks like. No Streamlit inside, so they are easy to test. |
| Data | `database.py`, `messaging_repository.py`, `database_setup.sql` | The only code that talks to Supabase. All tables are created by the one SQL file. |
| Look | `ui.py`, `messaging_ui.py`, `payment_ui.py`, `.streamlit/config.toml` | Shared design pieces: cards, colours, the chat bubbles, the payment box. |

**Why this split.** The pages only show things and pass on clicks. Every rule
lives in one plain Python file, which is called with the email from the login.
That keeps the rules in one place and lets the tests check them without a browser
or a real database.

### Where the data is stored

Everything is in **Supabase** (a hosted Postgres database plus file storage):

- **Tables:** `profiles`, `listings`, `favorites`, `reports`, `reviews`,
  `purchase_requests` (Buy Now deals), `conversations`, `messages`,
  `conversation_reads`, `offers` and `offer_operations`.
- **Photos:** two private storage buckets, `profile-photos` and
  `listing-photos`. The app hands out links that stop working after one hour.
- **Login:** **Auth0** holds the accounts and passwords. The app never sees a
  password; it only receives the confirmed email address.

Prices are stored as whole cents (1234 means €12.34), so there are no rounding
errors.

### What the tests cover, and what they miss

`pytest` runs more than 450 tests. They use a pretend database in memory
(`tests/fake_database.py`), so they need no internet and no keys.

**Covered:**

- The rules, both the actions that are allowed and the ones that are refused.
  For example: a non-Nova or unconfirmed email is refused, a blocked student
  can't sell, you can't report yourself, a price must be above zero (or the
  item free), an IBAN of the wrong shape is refused, an item can't be bought
  twice, and an unpaid deal is cancelled after 15 minutes.
- Photos: renamed files that aren't real images, other formats, files that are
  too big, and the GPS position being removed.
- The pages, with Streamlit's own test tool (`AppTest`): the right buttons and
  messages appear for the buyer and for the seller.

**Not covered:**

- The real Supabase database: its SQL functions, triggers and permissions are
  not run by the tests.
- The real Auth0 login and sending the confirmation email.
- How the pages look in a browser (colours and layout), and phones.
- Real money: the app never moves money. "I've paid" is the buyer's word, and
  the seller confirms after checking their bank.

### Security

- **Only Nova students.** Every page starts with `verified_nova_email()`: the
  email must end in `@novasbe.pt` and be confirmed in Auth0. Pages use that
  email, never one typed into a form.
- **Checked where the action happens.** The rules files check permissions again
  on every action (for example, only the seller can edit a listing and only the
  buyer can say they paid), not only by hiding buttons.
- **Admins** are listed in the secrets file, not in the code. Admins can remove
  listings and block accounts.
- **Secrets.** Keys live only in `.streamlit/secrets.toml` and in the host's
  settings, which are never committed. A check runs before every commit and on
  GitHub (`.githooks/`, `.github/workflows/`). The rules are in
  [AGENTS.md](AGENTS.md).
- **Database.** Row level security is on and there are no public policies, so
  the public Supabase key can't read anything. Only the app's server key can.
- **Input.** Titles, descriptions and prices have length and range checks.
  Everything a student typed is escaped before it is shown as HTML. Photos are
  re-saved without their hidden data, such as the GPS position.
- **IBAN.** It is shown only to a buyer after they tap Buy Now, never on a
  public profile.
- **Dependencies.** Only five packages, each pinned to an exact version in
  `requirements.txt`.

### If an outside service is down

- **Supabase down:** the menu counters fall back to zero, but pages that read
  listings or chats show an error until Supabase is back. Nothing is lost,
  because nothing is saved halfway: a purchase that fails puts the item back on
  sale.
- **Auth0 down:** nobody can sign in; students already signed in keep their
  session.

### Limits, and what could change next

- **Not instant.** Streamlit reloads the page; new messages and counters are
  checked every 5 seconds rather than pushed.
- **Deadlines need a visitor.** An unpaid deal is cancelled when someone opens
  the app, not at the exact minute.
- **No email notifications.** The next step would be an email when you receive
  an offer or a payment.
- **No real payments.** A payment provider such as Stripe or MB WAY could
  confirm payments automatically.
- **One database** is used for both testing and the live app. A separate test
  project in Supabase would make changes safer.
- **No account deletion yet.** It needs a rule for what happens to chats and
  reviews first.

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
shown only to that buyer. The buyer has 15 minutes to pay and tap "I've paid"
(cash: when they meet, no deadline), otherwise the purchase is cancelled and the
item is back on sale. The seller checks and taps "Payment received" (the item is
sold) or "Not received yet". The app never moves money itself. Unconfirmed offer
actions can be retried with the same operation ID.
