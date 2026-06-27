"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. These follow the same fixture and
assertion patterns as tests/test_collection.py.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    AlreadyInWatchlistError,
    NotInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """Adding a valid film should create a WatchlistEntry in the database."""
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Nonexistent film (Comment 3 — required) ───────────────────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)


# ── Sort order ────────────────────────────────────────────────────────────────

def test_get_watchlist_returns_newest_first(app, sample_user):
    """
    get_watchlist() should return films sorted by date_added descending
    (most recently added first).
    """
    with app.app_context():
        from datetime import datetime, timezone, timedelta

        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        entry_a = WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier)
        entry_b = WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later)
        db.session.add_all([entry_a, entry_b])
        db.session.commit()

        titles = [f["title"] for f in get_watchlist(sample_user)]

        # Blade Runner was added later, so it should come first.
        assert titles[0] == "Blade Runner"
        assert titles[1] == "Alien"


# ── Visibility default (Comment 4 behavior) ───────────────────────────────────

def test_add_to_watchlist_defaults_to_private(app, sample_user, sample_film):
    """New entries should be private by default; public is opt-in."""
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)
        assert entry.public is False

        public_film = Film(title="Casablanca", year=1942)
        db.session.add(public_film)
        db.session.commit()
        opted_in = add_to_watchlist(
            user_id=sample_user, film_id=public_film.id, public=True
        )
        assert opted_in.public is True


# ── Remove (stretch) ──────────────────────────────────────────────────────────

def test_remove_from_watchlist_deletes_entry(app, sample_user, sample_film):
    """Removing a film on the watchlist should delete the entry."""
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert remove_from_watchlist(user_id=sample_user, film_id=sample_film) is True
        assert get_watchlist(sample_user) == []


def test_remove_from_watchlist_not_present_raises(app, sample_user, sample_film):
    """Removing a film that isn't on the watchlist should raise NotInWatchlistError."""
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            remove_from_watchlist(user_id=sample_user, film_id=sample_film)


# ── Extra edge case (stretch) ─────────────────────────────────────────────────

def test_two_users_can_watchlist_the_same_film(app, sample_user, sample_film):
    """
    Deduplication is scoped to (user_id, film_id), not the film alone:
    two different users adding the same film is NOT a duplicate. This guards
    against an over-broad unique constraint that would let one user's
    watchlist block another's.
    """
    with app.app_context():
        other_user = User(username="other", email="other@example.com")
        db.session.add(other_user)
        db.session.commit()
        other_id = other_user.id

        add_to_watchlist(user_id=sample_user, film_id=sample_film)
        # Should not raise — different user, same film.
        add_to_watchlist(user_id=other_id, film_id=sample_film)

        total = WatchlistEntry.query.filter_by(film_id=sample_film).count()
        assert total == 2
