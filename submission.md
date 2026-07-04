# Submission Doc

## Codebase map

`app.py` - a standard Flask setup; there's a `create_app()` factory that sets up the database and registers four blueprints: songs, playlists, users, and feed. Each one gets its own URL prefix (`/songs`, `/playlists`, etc.). It calls `db.create_all()` on startup and defaults to a local SQLite file so there's no migration system to worry about.
`models.py` - most useful file for getting oriented. There are six tables: `User`, `Song`, `Tag`, `ListeningEvent`, `Rating`, `Playlist`, and `Notification`. A few things I had to look at twice:

- Playlists don't just store a list of songs — there's a separate `playlist_entries` join table that also tracks a `position` for each song, plus who added it and when. So the order of songs in a playlist is explicit, not just whatever order they got inserted.
- Ratings are their own table (`Rating`), with a constraint so one user can only rate a song once. I expected the rating might just be a number on the Song, but it's actually its own thing.

### Data flow: how a notification gets created

I traced the playlist one since it was the clearest example of things wiring together. When you `POST` a song to a playlist:

1. `routes/playlists.py` grabs the `song_id` and `added_by` from the request and calls `add_to_playlist()`.
2. That function (in `notification_service.py`) checks the song, user, and playlist all exist, then adds the song to the playlist if it's not already there.
3. Then it checks who originally *shared* the song. If someone other than the sharer added it to a playlist, it calls `create_notification()` to let the original sharer know.

So the notification goes to the person who first shared the song, and it skips the case where you add your own song.

### Patterns I noticed:

- Every model has a `to_dict()`, and that's always what gets sent back as JSON — the routes never build responses by hand.
- Each service commits to the database itself instead of leaving it to the caller.
- A lot of stuff (feeds, streaks) is derived from the raw event/listen data rather than stored as its own thing.
