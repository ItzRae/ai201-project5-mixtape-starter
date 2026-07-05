"""
tests/test_notifications.py — Mixtape

Tests for notification creation logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import add_to_playlist, rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_users_and_song(app):
    """Create a song sharer, another user, and a shared song."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        other_user = User(username="other_user", email="other@example.com")
        db.session.add_all([sharer, other_user])
        db.session.flush()

        song = Song(
            title="Test Track", artist="Test Artist",
            genre="test", shared_by=sharer.id
        )
        db.session.add(song)
        db.session.commit()

        yield {
            "sharer": sharer,
            "other_user": other_user,
            "song": song,
        }


def test_add_to_playlist_notifies_sharer(app, seed_users_and_song):
    """
    Adding a friend's shared song to a playlist should notify the sharer.
    This documents the existing, working notification pattern.

    Note: the song-to-playlist association is pre-inserted directly via
    playlist_entries (position/added_by set explicitly) rather than
    relying on add_to_playlist's own playlist.songs.append() call, since
    that call omits the NOT NULL position/added_by columns and is a
    separate, unrelated bug from the one under test here (issue #4 is
    about notifications, not playlist insertion).
    """
    from models import Playlist, playlist_entries
    from datetime import datetime, timezone

    with app.app_context():
        sharer = seed_users_and_song["sharer"]
        other_user = seed_users_and_song["other_user"]
        song = seed_users_and_song["song"]

        playlist = Playlist(name="Test Playlist", created_by=other_user.id)
        db.session.add(playlist)
        db.session.flush()

        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id,
                song_id=song.id,
                position=1,
                added_by=other_user.id,
                added_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()

        add_to_playlist(
            playlist_id=playlist.id,
            song_id=song.id,
            added_by_user_id=other_user.id,
        )

        notifications = get_notifications(sharer.id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_added_to_playlist"


def test_rate_song_notifies_sharer(app, seed_users_and_song):
    """
    Rating a friend's shared song should notify the sharer, the same way
    adding it to a playlist does. Fails before the fix (no notification
    is ever created), passes after.
    """
    with app.app_context():
        sharer = seed_users_and_song["sharer"]
        other_user = seed_users_and_song["other_user"]
        song = seed_users_and_song["song"]

        rate_song(user_id=other_user.id, song_id=song.id, score=5)

        notifications = get_notifications(sharer.id)
        assert len(notifications) == 1  # Bug: rate_song never calls create_notification
        assert notifications[0]["type"] == "song_rated"


def test_rate_song_does_not_notify_self(app, seed_users_and_song):
    """
    A user rating their own shared song should not receive a notification
    about it, mirroring the self-notification skip in add_to_playlist.
    """
    with app.app_context():
        sharer = seed_users_and_song["sharer"]
        song = seed_users_and_song["song"]

        rate_song(user_id=sharer.id, song_id=song.id, score=4)

        notifications = get_notifications(sharer.id)
        assert len(notifications) == 0