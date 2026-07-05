# Submission Doc

## AI Usage

### Reproducing before fixing: 

For each bug, I asked Claude to help design a reproduction step before touching code — e.g., specific datetime values to trigger the Sunday-only streak bug, and flask shell tests around the 24-hour cutoff for the "Friends Listening Now" issue.

### Tracing root causes: 

For the streak bug, I asked Claude to explain the purpose of `today.weekday() != 6` and why it was excluding Sundays then later realized that this was the whole bug - it was unnecessary and should not have excluded it. For the playlist bug, the existing failing test's diff made the off-by-one slice obvious with little extra tracing needed.

### Where it might've went wrong:

For the search duplication issue, I actually couldn't figure out how where the bug was and Claude was attempting to help by suggesting multiple directions but wasnt able to locate it either. Claude reasoned that the `outerjoin` on `song_tags` without `.distinct()` should produce duplicate rows for songs with multiple tags. I tested it directly and it didn't reproduce. After multiple attempts, I couldn't reproduce this one after a genuine attempt, so I moved to a different bug (last song in playlist) instead of forcing it.


### Verification I did myself: 
For every bug, I ran the actual test suite or manual reproduction before and after each fix rather than trusting predictions - this caught the search bug false positive and confirmed the notification fix by toggling it on/off and checking test results directly. For the playlist bug, the existing test failures already pointed at the last song being dropped; I found the songs[:-1] slice myself and Claude double check my write up and format for the root cause entry.



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

## ROOT CAUSE ANALYSIS

### Entry 1:

#### 1. Issue #1: "My listening streak keeps resetting"

#### 2. How I reproduced bug: 

Ran the existing test suite (`test_streaks.py`) before making any changes. `test_streak_increments_on_sunday` failed with assert 1 == 2: after calling `update_listening_streak` with a Saturday datetime (streak correctly set to 1), calling it again with the following Sunday's datetime left the streak at 1 instead of incrementing to 2. The other four tests in the file passed, confirming the bug was isolated to the Saturday→Sunday transition specifically - not a general failure of the increment or reset logic.

#### 3. How I found the root cause : 

I read `update_listening_streak` line by line, since it was the only function under test. The reset/increment branching is a single `if/elif/else` block, so I traced the exact condition being evaluated on the failing call: `days_since_last == 1` and `today.weekday() != 6`. With days_since_last correctly equal to 1 (Sat→Sun is one day apart), the only way to fall through to the else reset branch was the second half of that condition. Checking `datetime.weekday()`'s documented return values confirmed Sunday maps to 6, so `today.weekday() != 6` evaluates to `False `specifically and only on a Sunday so I was confident this was the exact cause

#### 4. the root cause:

The `elif` branch that increments the streak required `days_since_last == 1` and `today.weekday() != 6`. Python's `datetime.weekday()` returns 6 for Sunday, so this extra clause made the condition false whenever the current listen fell on a Sunday, regardless of how many consecutive days the user had actually listened. As a result, any streak update landing on a Sunday fell through to the else branch and reset the streak to 1 instead of incrementing it -- and the documented streak rules make no exception for Sunday.

#### 5. my fix and side-effect check :

Removed the `and today.weekday() != 6` clause so it just left `elif days_since_last == 1:` to increment the streak whenever exactly one day has passed. Re-ran the full `test_streaks.py` suite afterward: all five tests passed, including `test_streak_increments_on_consecutive_day` (Mon→Tue, confirms non-Sunday increments still work), `test_streak_does_not_double_count_same_day`, and `test_streak_resets_after_skipped_day` (confirms the reset branch for skipped days is untouched). This confirmed the fix corrected the Sunday case without affecting the same-day, consecutive-day, or gap-reset logic that shares the same function

-----

#### 1. Issue #5: The last song in a playlist never shows up

#### 2. How I reproduced bug: 

Ran the existing test suite (tests/test_playlists.py). Both functions (e.g `test_playlist_returns_all_songs` and the one returning songs in order) failed: a playlist seeded with 5 songs returned only 4 from `get_playlist_songs`, consistently missing the last entry ("Track 5") while the first four came back correctly and in the right order.

#### 3. How I found the root cause : 

Opened `services/playlist_service.py` and inspected `get_playlist_songs`, since it was the only function exercised by the failing tests. The function builds its return value from a songs list, and the final return line applied a `[:-1]` slice before converting to dicts — discarding the last element of the list regardless of playlist length. Confirming the slice was the cause was straightforward once I saw it: the ordering test showed exactly the first `N-1` songs in correct order, which is exactly what `songs[:-1]` produces.

#### 4: the root cause :

The return statement was `[song.to_dict() for song in songs[:-1]]`, which unconditionally drops the last item from the songs list before serializing. This meant get_playlist_songs would always omit whichever song occupied the final position.

#### 5: My fix and side-effect check:

Removed the `[:-1]` slice, changing the line to `[song.to_dict() for song in songs]` so all songs are included. Re-ran tests/test_playlists.py afterward: both previously failing tests now pass, returning all 5 songs in correct order. Also confirmed this change doesn't affect any other playlist logic.

-----

#### 1. Issue #4: No notification when a friend rates a shared song

#### 2. How I reproduced bug: 

Wrote `test_notifications.py` in `tests/` with a test that calls `rate_song()` on another user's shared song, then checks `get_notifications()` for the sharer. Before the fix, the notification count stayed at 0 : no notification was created.

#### 3. How I found the root cause:

Compared `rate_song()` to `add_to_playlist()` in `notification_service.py`, since both are meant to notify a song's sharer per the module docstring. I noticed `add_to_playlist()` calls `create_notification() `after its main operation but rate_song() does not call it anywhere.

#### 4. The root cause: 

`rate_song()` saves the Rating and commits, but never calls `create_notification().` The notify-on-rating behavior was simply never implemented.

#### 5. My fix and side-effect check:

Added a `create_notification()` call after the commit in `rate_song()`, using `notification_type="song_rated`", and skipping it when the rater is the song's own sharer (mirroring `add_to_playlist()`'s self-notification skip). Re-ran tests/`test_notifications.py`: all three tests pass, including confirmation that self-ratings don't trigger a notification and that playlist-add notifications still work unchanged

