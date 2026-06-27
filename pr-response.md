# PR Response Doc — CineLog Watchlist Feature

This document responds to the six review comments from @dev-lead, records the
two design decisions, and gives the PR description (feature overview + manual
testing steps).

---

## AI Usage

I used an AI assistant (Claude) in four bounded ways, all verified against the
actual code:

1. **Orientation.** I had it summarize `models.py`, `services/collection_service.py`,
   and `tests/test_collection.py` before reading the review comments, then
   checked each summary against the source. This is how I learned that
   `add_to_collection()` does an application-level `filter_by(...).first()` check
   *and* leans on a model-level `UniqueConstraint` — the pattern I mirrored for
   Comment 2.
2. **Conflict diagnosis.** After `git rebase origin/main` reported success, I had
   the AI help confirm my suspicion that the rebase had *silently* dropped
   `WatchlistEntry` from `models.py` (no conflict markers). I verified this
   myself by importing the app and watching it fail. See Comment 6.
3. **Commit hygiene.** I had it sanity-check my `git log --oneline` against the
   Conventional Commits spec and CONTRIBUTING.md (one logical change per commit).
4. **Devil's advocate on the design decisions (Comments 4 & 5).** I wrote my
   positions first, then asked: *"What counterargument would a careful reviewer
   raise, and what tradeoff am I not acknowledging?"* What changed as a result is
   noted inline in each of those comments below.

What the AI did **not** do: make the design decisions. The visibility default and
sort-order calls are mine; the reasoning is grounded in CineLog's specific
collection-vs-watchlist semantics.

---

## Comment 1 — Rename `save_to_watchlist()` → `add_to_watchlist()`

**What I did:**
Renamed the service function in `services/watchlist_service.py` and updated its
one call site, the import and the call in `routes/watchlist/watchlist.py`.

**How I verified:**
Project-wide search for the old name —
`grep -rn "save_to_watchlist" --include="*.py" .` — returned **no** matches after
the change, confirming there were no other call sites. I also re-imported the app
(`python -c "import app; app.create_app()"`) to confirm nothing broke.

**Why:** CONTRIBUTING.md specifies a `verb_to_noun` naming convention, and the
sibling function is `add_to_collection()`. `add_to_watchlist()` keeps the
public API of the two services symmetrical.

---

## Comment 2 — Deduplication

**What I did:**
Mirrored `add_to_collection()`'s approach exactly:
- Added an `AlreadyInWatchlistError` exception (parallel to `AlreadyInCollectionError`).
- In `add_to_watchlist()`, after the film-exists check, query for an existing
  `(user_id, film_id)` `WatchlistEntry`; if one exists, raise instead of inserting.
- Added a model-level `UniqueConstraint("user_id", "film_id",
  name="unique_user_film_watchlist")` to `WatchlistEntry` as the safety net —
  again matching `CollectionEntry`.
- Wired the add endpoint to translate service exceptions into HTTP codes:
  `FilmNotFoundError` → 404, `AlreadyInWatchlistError` → 409. (The base endpoint
  caught neither and would have returned a 500 for a missing film.)

**How I verified:**
A scratch script added the same film twice and asserted the second call raised
`AlreadyInWatchlistError` while the row count stayed at 1. Also covered by
`test_add_to_watchlist_duplicate_raises`. I confirmed the dedup is scoped to the
pair (not the film alone) with `test_two_users_can_watchlist_the_same_film`.

**Where I looked:** `add_to_collection()` in `services/collection_service.py:27`
for the existing check + exception pattern, and `CollectionEntry.__table_args__`
in `models.py` for the constraint.

---

## Comment 3 — Missing test

**What I did:**
Created `tests/test_watchlist.py`, modeled on `tests/test_collection.py` (same
`app` / `sample_user` / `sample_film` fixtures). The directly-requested test is
`test_add_to_watchlist_nonexistent_film_raises`, the equivalent of
`test_add_to_collection_nonexistent_film_raises`: it adds a film_id that doesn't
exist (a fake UUID) and asserts `FilmNotFoundError` is raised rather than a DB
integrity error. I also added the project-standard happy-path and duplicate tests
(CONTRIBUTING.md asks for all three for a new service function), plus sort,
visibility, and remove coverage.

**How I verified:**
`pytest tests/test_watchlist.py -v` and `pytest tests/ -v` — **12 passed**
(4 collection + 8 watchlist). The model test was
`test_add_to_collection_nonexistent_film_raises`; I reused its fixture structure
and fake-UUID assertion.

---

## Comment 4 — Default visibility (`public`)

**My position:** Default to **private** — `WatchlistEntry.public` defaults to
`False`. (Code change in `models.py`; the new `public` parameter on
`add_to_watchlist()` lets callers opt in.)

**Reasoning (CineLog-specific):**
A *collection* and a *watchlist* are not the same kind of object. The collection
is a retrospective log of films already watched — a relatively low-stakes signal.
A watchlist is forward-looking: it broadcasts **intent**, and intent is more
revealing than history. "Planning to watch" a specific political documentary, a
film tied to a health diagnosis, or a particular pairing of titles can leak
something a user never meant to publish. The user who just wants a private
"save for later" queue is the user who will *never read the docs* to discover a
visibility setting — so the default has to protect them. They should opt **in**
to sharing, not have to discover an opt-out.

The deciding factor is **reversibility asymmetry**: a watchlist that defaults
public can't truly be un-shared once someone has seen it, whereas a watchlist
that defaults private costs exactly one toggle to publish. When one default's
failure mode is irreversible and the other's is a single click, you default to
the reversible, lower-harm state.

**Tradeoff acknowledged:** CineLog is explicitly a *community* app, and a
private-by-default watchlist removes social-graph signal that powers discovery
features like "what your friends want to watch." We give up some default
engagement. I mitigate this by making sharing a **first-class, low-friction
opt-in** rather than a buried setting: the `public` parameter on the add endpoint
(stretch feature) lets a client publish an entry in the same request, so the
"I want this public" path is one field, not a separate visit to settings.

**What the devil's-advocate pass changed:** My first draft argued only "privacy
is safer." The AI pushed back that for a *community* product, private-by-default
could read as fighting the platform's purpose and starving discovery. That's a
real cost, so I added the explicit mitigation (the opt-in `public` parameter) and
reframed the argument around reversibility rather than a blanket "privacy wins."

---

## Comment 5 — Sort order

**My position:** **Agree with the maintainer** — switch from alphabetical
(`Film.title.asc()`) to **date-added, newest first** (`date_added.desc()`).
Implemented in `get_watchlist()`.

**Engagement with the reviewer's point:**
The maintainer's reasoning is consistency with `get_collection()`, which already
sorts `date_added.desc()`. I agree, and I'd strengthen it with a product reason:
a watchlist is a **queue of intent**, not a reference catalog. The question a
user actually asks their watchlist is "what should I watch next / what did I just
add?" — not "where's the title starting with B?" Newest-first answers that
directly and also gives immediate UX confirmation that an add worked (the film
you just queued appears at the top instead of being buried mid-alphabet).

I took the alphabetical case seriously: in a long list, A–Z helps you *locate a
known title*. But that's a search/filter problem, better solved by a search box
or the existing genre filter than by imposing a global sort that hurts the common
"what's next" case. And the consistency point is not cosmetic — a user flipping
between `/collection` and `/watchlist` shouldn't have to hold two different mental
models of ordering.

I considered a third option — a `?sort=date|title` query parameter — and
**rejected it for now** as premature: it adds API surface and client branching
before there's any evidence users want to re-sort. I've noted it as a clean
future extension if that evidence appears.

**What the devil's-advocate pass changed:** The AI raised the "long-list
findability" counterargument for alphabetical. Rather than ignore it, I
addressed it head-on (it's a search concern, not a sort concern) and added the
`?sort=` option as an explicit, deliberately-deferred future path.

---

## Comment 6 — Rebase onto updated main

**What conflicted:**
`feature/watchlist` branched *before* the `main` refactor that migrated film IDs
from integer to UUID. The interesting part: `git rebase origin/main` reported
**"Successfully rebased"** with no conflict markers — but it had **silently
dropped the entire `WatchlistEntry` class** from `models.py`. The refactor edited
the `Film.id` and `CollectionEntry.film_id` columns in the same region of the
file where my `WatchlistEntry` had been added, and the three-way auto-merge
resolved that overlap by keeping `main`'s version of that region and discarding
my addition. The result imported-but-broke: `services/watchlist_service.py` still
did `from models import ... WatchlistEntry`, raising `ImportError`.

**How I resolved it:**
- Re-added `WatchlistEntry` to `models.py`, with `film_id` as
  `db.Column(db.String(36), db.ForeignKey("film.id"))` — UUID, matching the
  refactored `Film.id` — instead of the original `db.Integer`.
- Updated the now-stale `film_id (int)` docstrings in the service and the
  `Body: { "film_id": <int> }` hint in the route to say UUID.
- Scoped the PR back down: the pre-rebase branch had also changed
  `services/collection_service.py` to use `db.session.get`. That's unrelated to
  the watchlist, so I reverted that file to `main`'s version (`git checkout
  origin/main -- services/collection_service.py`). The watchlist service keeps
  `db.session.get` (the non-deprecated API) on its own.

**How I verified no conflict remains:**
- `python -c "import app; app.create_app()"` imports cleanly.
- `pytest tests/ -v` → 12 passed.
- `git log --merges origin/main..HEAD` is **empty** — no merge commits.
- `git merge-base HEAD origin/main` equals `origin/main`'s tip, i.e. the branch
  is linear, sitting directly on top of the UUID `main`.
- `git diff --stat origin/main..HEAD` touches only watchlist files + `.gitignore`
  + `pr-response.md` — `collection_service.py` is not in the diff.

---

## Stretch Features

**`remove_from_watchlist(user_id, film_id)`** — mirrors `remove_from_collection`:
deletes the `(user_id, film_id)` entry and returns `True`, or raises
`NotInWatchlistError`. Exposed as `DELETE /watchlist/<user_id>/remove`. Tested by
`test_remove_from_watchlist_deletes_entry` and
`test_remove_from_watchlist_not_present_raises`.

**Extra test — `test_two_users_can_watchlist_the_same_film`.** I chose this edge
case because the dedup work introduced a unique constraint, and the subtle risk
with a constraint is making it *too broad*. This test proves dedup is scoped to
the `(user_id, film_id)` pair: two different users adding the same film is not a
duplicate. It's the test that would catch a regression where someone "simplified"
the constraint down to `film_id` alone and accidentally let one user's watchlist
block everyone else's.

**Visibility toggle parameter.** Added an optional `public` parameter to
`add_to_watchlist()` (default `False`, matching the model default) and read it
from the request body (`data.get("public", False)`). This makes sharing an
explicit opt-in in the same request, which is the mitigation referenced in
Comment 4. Tested by `test_add_to_watchlist_defaults_to_private`.

---

## Commit History

Rewritten into Conventional Commits, one logical change per commit, no merge
commits. The original branch's two messy commits ("added watchlist model and
endpoint fixed a bug more changes" and a follow-up) were restructured into the
clean set below during the rebase cleanup.

```
<HEAD>  docs: add pr-response.md with review responses and design decisions
ac5e25a test: add watchlist service tests
b15e0c0 feat: allow callers to set watchlist visibility on add
7b110f7 feat: add remove_from_watchlist service and endpoint
5fba49c fix: sort watchlist by date added, newest first
0bf9424 fix: add film relationship to WatchlistEntry
4bf9d1b fix: default new watchlist entries to private
592f215 fix: prevent duplicate films on a watchlist
b39e233 fix: rename save_to_watchlist to add_to_watchlist for naming consistency
c103d7a feat: add watchlist model, service, and endpoints
3c0497a chore: add .gitignore for venv, pycache, and sqlite db
```

<img width="940" height="197" alt="git log" src="https://github.com/user-attachments/assets/f56a196f-abd0-4863-9dec-015c6db41c74" />


---

## PR Description

### What the watchlist feature does
Adds a per-user **watchlist** — films a user wants to watch later, distinct from
the collection of films they've already watched. Users can add a film, remove a
film, and view their watchlist. Each entry stores who added it, the film, when it
was added, and whether it's publicly visible. Entries are deduplicated per user
and films are validated to exist before being added.

**Endpoints**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/watchlist/<user_id>` | View a user's watchlist (newest first) |
| POST | `/watchlist/<user_id>/add` | Add a film. Body: `{"film_id": "<uuid>", "public": false}` (`public` optional) |
| DELETE | `/watchlist/<user_id>/remove` | Remove a film. Body: `{"film_id": "<uuid>"}` |

### Design decisions
1. **Visibility defaults to private (`public=False`).** A watchlist broadcasts
   intent, which is more sensitive than watch history, and an accidentally-public
   list can't be un-shared. Sharing is a one-field opt-in via the `public`
   parameter. (Full reasoning: Comment 4.)
2. **Sorted newest-first by date added,** matching `get_collection()` and
   treating the watchlist as a recency-ordered queue rather than an alphabetical
   catalog. (Full reasoning: Comment 5.)

### How to test it manually
```bash
# 1. Set up and run
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # serves http://127.0.0.1:5000 (no frontend; 404 at / is expected)

# 2. Seed a user and a film, and grab their UUIDs (in a second terminal)
python - <<'PY'
from app import create_app, db
from models import User, Film
app = create_app()
with app.app_context():
    u = User(username="ada", email="ada@example.com")
    f = Film(title="Arrival", year=2016, genre="Sci-Fi")
    db.session.add_all([u, f]); db.session.commit()
    print("USER_ID =", u.id)
    print("FILM_ID =", f.id)
PY

# 3. Exercise the endpoints (substitute the UUIDs printed above)
USER=<user-uuid>; FILM=<film-uuid>

# Add (defaults to private)
curl -s -X POST http://127.0.0.1:5000/watchlist/$USER/add \
  -H "Content-Type: application/json" -d "{\"film_id\": \"$FILM\"}"
# -> 201, JSON entry with "public": false

# Add again -> 409 duplicate
curl -s -X POST http://127.0.0.1:5000/watchlist/$USER/add \
  -H "Content-Type: application/json" -d "{\"film_id\": \"$FILM\"}"

# Add a nonexistent film -> 404
curl -s -X POST http://127.0.0.1:5000/watchlist/$USER/add \
  -H "Content-Type: application/json" -d "{\"film_id\": \"00000000-0000-0000-0000-000000000000\"}"

# View (newest first)
curl -s http://127.0.0.1:5000/watchlist/$USER

# Remove
curl -s -X DELETE http://127.0.0.1:5000/watchlist/$USER/remove \
  -H "Content-Type: application/json" -d "{\"film_id\": \"$FILM\"}"
# -> 200 {"message": "Removed from watchlist"}

# 4. Or just run the tests
pytest tests/ -v        # 12 passed
```
