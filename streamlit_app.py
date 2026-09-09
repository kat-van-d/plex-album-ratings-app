import streamlit as st
from supabase import create_client, Client
import pandas as pd
import requests
import re
import unicodedata
from difflib import SequenceMatcher


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Plex Album Ratings",
    page_icon="🎵",
    layout="wide",
)


# ============================================================
# SUPABASE CONNECTION
# ============================================================

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
LASTFM_API_KEY = st.secrets.get("LASTFM_API_KEY", "")

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
)


# ============================================================
# SESSION STATE
# ============================================================

def ensure_session():
    defaults = {
        "access_token": None,
        "refresh_token": None,
        "user_id": None,
        "user_email": None,
        "display_name": None,
        "selected_album_id": None,
        "app_page": "Albums",
        "lastfm_results": None,
        "lastfm_results_key": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def set_supabase_session():
    if (
        st.session_state.access_token
        and st.session_state.refresh_token
    ):
        supabase.auth.set_session(
            st.session_state.access_token,
            st.session_state.refresh_token,
        )


def sign_out():
    try:
        set_supabase_session()
        supabase.auth.sign_out()
    except Exception:
        pass

    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.user_id = None
    st.session_state.user_email = None
    st.session_state.display_name = None
    st.session_state.selected_album_id = None

    st.rerun()


# ============================================================
# HELPERS
# ============================================================

def relation_one(value):
    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        if len(value) > 0:
            return value[0]

    return {}


def truncate_text(text, max_chars):
    text = text or ""

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 1].rstrip() + "…"


def render_artwork(artwork_url):
    if artwork_url:
        st.image(
            artwork_url,
            use_container_width=True,
        )
    else:
        # Native placeholder with no raw HTML.
        with st.container(
            height=220,
            border=True,
        ):
            st.write("")
            st.write("")
            st.write("")
            st.markdown(
                "### 🎵"
            )


def render_album_card(
    row,
    reviewed_by_album,
):
    artwork_url = row.get("artwork_url")

    artist_data = relation_one(
        row.get("artists")
    )

    artist = (
        artist_data.get("name")
        or "Unknown artist"
    )

    title = (
        row.get("title")
        or "Untitled"
    )

    year = row.get("year")

    review = reviewed_by_album.get(
        row["album_id"]
    )

    render_artwork(
        artwork_url
    )

    # Fixed-height native container keeps the text area aligned.
    with st.container(
        height=170,
        border=False,
    ):
        st.markdown(
            f"**{truncate_text(title, 42)}**"
        )

        st.caption(
            truncate_text(
                artist,
                34,
            )
        )

        if year:
            st.caption(
                str(year)
            )
        else:
            st.caption(" ")

        if (
            review
            and review.get("rating") is not None
        ):
            st.caption(
                f"Your rating: "
                f"{review['rating']}/5"
            )
        else:
            st.caption(
                "Not yet rated"
            )

    if st.button(
        "Open",
        key=f"open_{row['album_id']}",
        use_container_width=True,
    ):
        st.session_state.selected_album_id = (
            row["album_id"]
        )

        st.rerun()


def render_album_list_row(
    row,
    reviewed_by_album,
):
    artwork_url = row.get("artwork_url")
    artist_data = relation_one(row.get("artists"))
    artist = artist_data.get("name") or "Unknown artist"
    title = row.get("title") or "Untitled"
    year = row.get("year")
    review = reviewed_by_album.get(row["album_id"])

    with st.container(border=True):
        image_col, info_col, action_col = st.columns([1, 4, 1.2], vertical_alignment="center")

        with image_col:
            if artwork_url:
                st.image(artwork_url, use_container_width=True)
            else:
                with st.container(height=100, border=True):
                    st.markdown("### 🎵")

        with info_col:
            st.markdown(f"### {title}")
            metadata = [artist]
            if year:
                metadata.append(str(year))
            st.caption(" • ".join(metadata))

            if review and review.get("rating") is not None:
                st.write(f"Your rating: **{review['rating']}/5**")
            else:
                st.caption("Not yet rated")

            if review and (review.get("notes") or "").strip():
                st.caption(truncate_text(review.get("notes") or "", 180))

        with action_col:
            if st.button(
                "Open album",
                key=f"open_list_{row['album_id']}",
                use_container_width=True,
            ):
                st.session_state.selected_album_id = row["album_id"]
                st.rerun()


# ============================================================
# LAST.FM HELPERS
# ============================================================

def normalize_music_name(value):
    """Normalize artist/album text for conservative catalog matching."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_album_edition(value):
    """Remove only clearly edition-related trailing qualifiers."""
    value = value or ""
    edition_words = (
        "remaster|remastered|deluxe|expanded|anniversary|"
        "bonus|edition|reissue|special edition"
    )
    value = re.sub(
        rf"\s*[\(\[][^\)\]]*(?:{edition_words})[^\)\]]*[\)\]]\s*$",
        "", value, flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"\s*[-–—:]\s*.*(?:{edition_words}).*$",
        "", value, flags=re.IGNORECASE,
    )
    return normalize_music_name(value)


def fetch_lastfm_top_albums(username, period="3month", limit=100):
    if not LASTFM_API_KEY:
        raise RuntimeError("LASTFM_API_KEY is not configured in Streamlit secrets.")

    response = requests.get(
        LASTFM_API_URL,
        params={
            "method": "user.gettopalbums",
            "user": username,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "period": period,
            "limit": limit,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if "error" in payload:
        raise RuntimeError(payload.get("message") or f"Last.fm API error {payload['error']}")

    albums = payload.get("topalbums", {}).get("album", [])
    results = []
    for index, album in enumerate(albums, start=1):
        artist_data = album.get("artist") or {}
        results.append({
            "rank": index,
            "album": album.get("name") or "Untitled",
            "artist": artist_data.get("name") or "Unknown artist",
            "playcount": int(album.get("playcount") or 0),
            "lastfm_mbid": album.get("mbid") or None,
            "lastfm_url": album.get("url") or None,
        })
    return results


def build_plex_album_index(albums):
    exact_index = {}
    edition_index = {}
    by_artist = {}
    for album in albums:
        artist_data = relation_one(album.get("artists"))
        artist = artist_data.get("name") or ""
        title = album.get("title") or ""
        artist_key = normalize_music_name(artist)
        album_key = normalize_music_name(title)
        edition_key = normalize_album_edition(title)
        exact_index.setdefault((artist_key, album_key), []).append(album)
        edition_index.setdefault((artist_key, edition_key), []).append(album)
        by_artist.setdefault(artist_key, []).append(album)
    return exact_index, edition_index, by_artist


def match_lastfm_album(lastfm_album, indexes):
    exact_index, edition_index, by_artist = indexes
    artist_key = normalize_music_name(lastfm_album["artist"])
    album_key = normalize_music_name(lastfm_album["album"])
    edition_key = normalize_album_edition(lastfm_album["album"])

    exact = exact_index.get((artist_key, album_key), [])
    if len(exact) == 1:
        return exact[0], "Exact"

    edition = edition_index.get((artist_key, edition_key), [])
    if len(edition) == 1:
        return edition[0], "Edition-normalized"

    scored = []
    for candidate in by_artist.get(artist_key, []):
        candidate_key = normalize_music_name(candidate.get("title") or "")
        score = SequenceMatcher(None, album_key, candidate_key).ratio()
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    if scored and scored[0][0] >= 0.94:
        runner_up = scored[1][0] if len(scored) > 1 else 0
        if scored[0][0] - runner_up >= 0.03:
            return scored[0][1], "High-confidence fuzzy"

    return None, None


def compare_lastfm_to_plex(lastfm_albums, plex_albums):
    indexes = build_plex_album_index(plex_albums)
    compared = []
    for item in lastfm_albums:
        match, match_method = match_lastfm_album(item, indexes)
        compared.append({
            **item,
            "in_plex": match is not None,
            "plex_album_id": match.get("album_id") if match else None,
            "plex_album_title": match.get("title") if match else None,
            "match_method": match_method,
        })
    return compared


def get_my_profile():
    response = (
        supabase.table("profiles")
        .select("display_name,lastfm_username")
        .eq("user_id", st.session_state.user_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else {}


def save_lastfm_username(username):
    (
        supabase.table("profiles")
        .update({"lastfm_username": username or None})
        .eq("user_id", st.session_state.user_id)
        .execute()
    )
    st.session_state.lastfm_results = None
    st.session_state.lastfm_results_key = None


# ============================================================
# AUTHENTICATION
# ============================================================

def login_page():
    st.title("🎵 Plex Album Ratings")

    st.write(
        "Sign in to browse the Plex music library, "
        "rate albums, and save your notes."
    )

    login_tab, signup_tab = st.tabs(
        ["Sign in", "Create account"]
    )

    with login_tab:
        with st.form("login_form"):
            email = st.text_input(
                "Email",
                key="login_email",
            )

            password = st.text_input(
                "Password",
                type="password",
                key="login_password",
            )

            submitted = st.form_submit_button(
                "Sign in",
                use_container_width=True,
            )

        if submitted:
            try:
                response = supabase.auth.sign_in_with_password(
                    {
                        "email": email.strip(),
                        "password": password,
                    }
                )

                st.session_state.access_token = (
                    response.session.access_token
                )

                st.session_state.refresh_token = (
                    response.session.refresh_token
                )

                st.session_state.user_id = response.user.id
                st.session_state.user_email = response.user.email

                set_supabase_session()

                profile_response = (
                    supabase
                    .table("profiles")
                    .select("display_name,lastfm_username")
                    .eq(
                        "user_id",
                        response.user.id,
                    )
                    .limit(1)
                    .execute()
                )

                if profile_response.data:
                    profile = profile_response.data[0]

                    st.session_state.display_name = (
                        profile.get("display_name")
                    )

                st.rerun()

            except Exception as exc:
                st.error(
                    f"Sign in failed: {exc}"
                )

    with signup_tab:
        with st.form("signup_form"):
            display_name = st.text_input(
                "Display name",
                key="signup_display_name",
            )

            email = st.text_input(
                "Email",
                key="signup_email",
            )

            password = st.text_input(
                "Password",
                type="password",
                key="signup_password",
            )

            submitted = st.form_submit_button(
                "Create account",
                use_container_width=True,
            )

        if submitted:
            try:
                response = supabase.auth.sign_up(
                    {
                        "email": email.strip(),
                        "password": password,
                        "options": {
                            "data": {
                                "display_name":
                                    display_name.strip()
                            }
                        },
                    }
                )

                if response.session:
                    st.session_state.access_token = (
                        response.session.access_token
                    )

                    st.session_state.refresh_token = (
                        response.session.refresh_token
                    )

                    st.session_state.user_id = response.user.id
                    st.session_state.user_email = response.user.email
                    st.session_state.display_name = display_name.strip()

                    st.success(
                        "Account created successfully."
                    )

                    st.rerun()

                else:
                    st.success(
                        "Account created. Check your email "
                        "for the confirmation link, then "
                        "return here and sign in."
                    )

            except Exception as exc:
                st.error(
                    f"Account creation failed: {exc}"
                )


# ============================================================
# DATA RETRIEVAL
# ============================================================

def get_all_albums():
    all_rows = []

    page_size = 1000
    start = 0

    while True:
        response = (
            supabase
            .table("albums")
            .select(
                "album_id,"
                "title,"
                "year,"
                "studio,"
                "summary,"
                "artwork_url,"
                "musicbrainz_release_group_id,"
                "artist_id,"
                "artists(name)"
            )
            .range(
                start,
                start + page_size - 1,
            )
            .execute()
        )

        batch = response.data or []
        all_rows.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return all_rows


def get_user_reviews():
    response = (
        supabase
        .table("album_reviews")
        .select(
            "album_id,"
            "rating,"
            "notes"
        )
        .eq(
            "user_id",
            st.session_state.user_id,
        )
        .execute()
    )

    return response.data or []


def get_album_detail(album_id):
    response = (
        supabase
        .table("albums")
        .select(
            "album_id,"
            "title,"
            "year,"
            "studio,"
            "summary,"
            "artwork_url,"
            "rating,"
            "plex_user_rating,"
            "artist_id,"
            "artists(name)"
        )
        .eq(
            "album_id",
            album_id,
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def get_tracks(album_id):
    response = (
        supabase
        .table("tracks")
        .select(
            "track_id,"
            "track_number,"
            "title,"
            "duration_human,"
            "audio_codec,"
            "bitrate,"
            "view_count"
        )
        .eq(
            "album_id",
            album_id,
        )
        .order(
            "track_number"
        )
        .execute()
    )

    return response.data or []


def get_my_review(album_id):
    response = (
        supabase
        .table("album_reviews")
        .select(
            "review_id,"
            "rating,"
            "notes"
        )
        .eq(
            "album_id",
            album_id,
        )
        .eq(
            "user_id",
            st.session_state.user_id,
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return {}


def get_community_reviews(album_id):
    response = (
        supabase
        .table("album_reviews")
        .select(
            "rating,"
            "notes,"
            "user_id,"
            "profiles(display_name)"
        )
        .eq(
            "album_id",
            album_id,
        )
        .execute()
    )

    return response.data or []


def get_my_track_note(track_id):
    response = (
        supabase
        .table("track_notes")
        .select(
            "track_note_id,"
            "notes"
        )
        .eq(
            "track_id",
            track_id,
        )
        .eq(
            "user_id",
            st.session_state.user_id,
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return {}


def get_community_track_notes(track_id):
    response = (
        supabase
        .table("track_notes")
        .select(
            "notes,"
            "user_id,"
            "profiles(display_name)"
        )
        .eq(
            "track_id",
            track_id,
        )
        .execute()
    )

    return response.data or []


def get_all_my_album_notes():
    response = (
        supabase
        .table("album_reviews")
        .select(
            "review_id,"
            "album_id,"
            "rating,"
            "notes,"
            "created_at,"
            "updated_at,"
            "albums(title,year,artwork_url,artists(name))"
        )
        .eq(
            "user_id",
            st.session_state.user_id,
        )
        .execute()
    )

    return [
        row
        for row in (response.data or [])
        if (row.get("notes") or "").strip()
    ]


def get_all_my_track_notes():
    response = (
        supabase
        .table("track_notes")
        .select(
            "track_note_id,"
            "track_id,"
            "notes,"
            "created_at,"
            "updated_at,"
            "tracks(title,track_number,album_id,albums(title,year,artwork_url,artists(name)))"
        )
        .eq(
            "user_id",
            st.session_state.user_id,
        )
        .execute()
    )

    return [
        row
        for row in (response.data or [])
        if (row.get("notes") or "").strip()
    ]


def get_all_community_album_notes():
    """Return all non-empty album notes visible to the signed-in user."""
    all_rows = []
    page_size = 1000
    start = 0

    while True:
        response = (
            supabase
            .table("album_reviews")
            .select(
                "review_id,"
                "album_id,"
                "user_id,"
                "rating,"
                "notes,"
                "created_at,"
                "updated_at,"
                "profiles(display_name),"
                "albums(title,year,artwork_url,artists(name))"
            )
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = response.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size

    return [
        row for row in all_rows
        if (row.get("notes") or "").strip()
    ]


def get_all_community_track_notes():
    """Return all non-empty track notes visible to the signed-in user."""
    all_rows = []
    page_size = 1000
    start = 0

    while True:
        response = (
            supabase
            .table("track_notes")
            .select(
                "track_note_id,"
                "track_id,"
                "user_id,"
                "notes,"
                "created_at,"
                "updated_at,"
                "profiles(display_name),"
                "tracks(title,track_number,album_id,albums(title,year,artwork_url,artists(name)))"
            )
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = response.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size

    return [
        row for row in all_rows
        if (row.get("notes") or "").strip()
    ]


def get_all_album_ratings():
    """Return all visible album ratings with album and profile metadata."""
    all_rows = []
    page_size = 1000
    start = 0

    while True:
        response = (
            supabase
            .table("album_reviews")
            .select(
                "review_id,"
                "album_id,"
                "user_id,"
                "rating,"
                "updated_at,"
                "profiles(display_name),"
                "albums(title,year,artwork_url,artists(name))"
            )
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = response.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size

    return [
        row for row in all_rows
        if row.get("rating") is not None
    ]


# ============================================================
# SIDEBAR
# ============================================================

def render_sidebar_identity():
    with st.sidebar:
        st.header("Music Library")
        user_label = (
            st.session_state.display_name
            or st.session_state.user_email
            or "Signed-in user"
        )
        st.caption(f"Signed in as {user_label}")
        if st.button("Sign out", use_container_width=True, key="sidebar_sign_out"):
            sign_out()
        st.divider()
        st.radio("View", ["Albums", "Notes", "Top Rated", "Last.fm Audit"], key="app_page")
        st.divider()


def sidebar_filters(albums):
    render_sidebar_identity()

    with st.sidebar:

        search = st.text_input(
            "Search albums or artists"
        )

        years = sorted(
            {
                row.get("year")
                for row in albums
                if row.get("year") is not None
            }
        )

        year_choice = st.selectbox(
            "Year",
            ["All"] + [
                str(year)
                for year in years
            ],
        )

        sort_choice = st.selectbox(
            "Sort",
            [
                "Artist / Album",
                "Album title",
                "Year (newest)",
                "Year (oldest)",
            ],
        )

        only_unrated = st.checkbox(
            "Only albums I haven't rated"
        )

        display_choice = st.radio(
            "Display",
            ["Grid", "List"],
            horizontal=True,
            key="album_display_mode",
        )

    return (
        search.strip(),
        year_choice,
        sort_choice,
        only_unrated,
        display_choice,
    )


# ============================================================
# ALBUM BROWSER
# ============================================================

def album_browser():
    set_supabase_session()

    albums = get_all_albums()

    (
        search,
        year_choice,
        sort_choice,
        only_unrated,
        display_choice,
    ) = sidebar_filters(albums)

    st.title("Albums")

    reviews = get_user_reviews()

    reviewed_by_album = {
        review["album_id"]: review
        for review in reviews
    }

    rows = albums.copy()

    if search:
        search_lower = search.lower()
        filtered_rows = []

        for row in rows:
            artist_data = relation_one(
                row.get("artists")
            )

            artist_name = (
                artist_data.get("name")
                or ""
            )

            album_title = (
                row.get("title")
                or ""
            )

            if (
                search_lower in album_title.lower()
                or search_lower in artist_name.lower()
            ):
                filtered_rows.append(row)

        rows = filtered_rows

    if year_choice != "All":
        selected_year = int(
            year_choice
        )

        rows = [
            row
            for row in rows
            if row.get("year") == selected_year
        ]

    if only_unrated:
        rows = [
            row
            for row in rows
            if row["album_id"]
            not in reviewed_by_album
        ]

    if sort_choice == "Artist / Album":
        rows.sort(
            key=lambda row: (
                (
                    relation_one(
                        row.get("artists")
                    ).get("name")
                    or ""
                ).lower(),
                (
                    row.get("title")
                    or ""
                ).lower(),
            )
        )

    elif sort_choice == "Album title":
        rows.sort(
            key=lambda row: (
                row.get("title")
                or ""
            ).lower()
        )

    elif sort_choice == "Year (newest)":
        rows.sort(
            key=lambda row:
                row.get("year") or 0,
            reverse=True,
        )

    elif sort_choice == "Year (oldest)":
        rows.sort(
            key=lambda row:
                row.get("year") or 9999
        )

    st.caption(
        f"{len(rows):,} albums shown"
    )

    if not rows:
        st.info(
            "No albums match the current filters."
        )
        return

    if display_choice == "List":
        for row in rows:
            render_album_list_row(
                row,
                reviewed_by_album,
            )
        return

    columns_per_row = 4

    for start in range(
        0,
        len(rows),
        columns_per_row,
    ):
        album_row = rows[
            start:
            start + columns_per_row
        ]

        columns = st.columns(
            columns_per_row,
            gap="medium",
        )

        for column, row in zip(
            columns,
            album_row,
        ):
            with column:
                render_album_card(
                    row,
                    reviewed_by_album,
                )


# ============================================================
# NOTES PAGE
# ============================================================

def notes_page():
    set_supabase_session()
    render_sidebar_identity()

    st.title("Notes")
    st.write(
        "Browse album and track notes grouped by album. View your own notes, "
        "notes from everyone, or notes from a specific user."
    )

    try:
        album_notes = get_all_community_album_notes()
        track_notes = get_all_community_track_notes()
    except Exception as exc:
        st.error(f"Could not load notes: {exc}")
        return

    rows = []

    for row in album_notes:
        album = relation_one(row.get("albums"))
        artist_data = relation_one(album.get("artists"))
        profile = relation_one(row.get("profiles"))
        user_id = row.get("user_id")
        display_name = (
            profile.get("display_name")
            or ("You" if user_id == st.session_state.user_id else "User")
        )
        rows.append({
            "note_type": "Album note",
            "album_id": row.get("album_id"),
            "user_id": user_id,
            "display_name": display_name,
            "artist": artist_data.get("name") or "Unknown artist",
            "album": album.get("title") or "Untitled",
            "year": album.get("year"),
            "artwork_url": album.get("artwork_url"),
            "track": None,
            "track_number": None,
            "rating": row.get("rating"),
            "notes": row.get("notes") or "",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        })

    for row in track_notes:
        track = relation_one(row.get("tracks"))
        album = relation_one(track.get("albums"))
        artist_data = relation_one(album.get("artists"))
        profile = relation_one(row.get("profiles"))
        user_id = row.get("user_id")
        display_name = (
            profile.get("display_name")
            or ("You" if user_id == st.session_state.user_id else "User")
        )
        rows.append({
            "note_type": "Track note",
            "album_id": track.get("album_id"),
            "user_id": user_id,
            "display_name": display_name,
            "artist": artist_data.get("name") or "Unknown artist",
            "album": album.get("title") or "Untitled",
            "year": album.get("year"),
            "artwork_url": album.get("artwork_url"),
            "track": track.get("title") or "Untitled track",
            "track_number": track.get("track_number"),
            "rating": None,
            "notes": row.get("notes") or "",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        })

    if not rows:
        st.info("No album or track notes have been written yet.")
        return

    # Build a stable list of people who actually have notes.
    people = {}
    for row in rows:
        user_id = row.get("user_id")
        if user_id:
            people[user_id] = row.get("display_name") or "User"

    sorted_people = sorted(
        people.items(),
        key=lambda item: (
            0 if item[0] == st.session_state.user_id else 1,
            (item[1] or "").lower(),
        ),
    )

    scope_options = ["My notes", "Everyone"]
    scope_to_user = {}
    used_labels = set(scope_options)

    for user_id, name in sorted_people:
        if user_id == st.session_state.user_id:
            continue
        label = name
        if label in used_labels:
            label = f"{name} ({str(user_id)[:8]})"
        used_labels.add(label)
        scope_options.append(label)
        scope_to_user[label] = user_id

    controls_scope, controls_search, controls_type, controls_sort = st.columns([1.2, 2, 1, 1])

    with controls_scope:
        scope = st.selectbox("Whose notes", scope_options)

    with controls_search:
        search = st.text_input(
            "Search notes",
            placeholder="Search notes, users, artists, albums, or tracks",
        ).strip().lower()

    with controls_type:
        note_type = st.selectbox(
            "Type",
            ["All", "Album notes", "Track notes"],
        )

    with controls_sort:
        sort_choice = st.selectbox(
            "Sort albums",
            ["Recently updated", "Oldest updated", "Artist / Album"],
        )

    if scope == "My notes":
        visible = [
            row for row in rows
            if row.get("user_id") == st.session_state.user_id
        ]
    elif scope == "Everyone":
        visible = rows.copy()
    else:
        selected_user_id = scope_to_user.get(scope)
        visible = [
            row for row in rows
            if row.get("user_id") == selected_user_id
        ]

    if note_type == "Album notes":
        visible = [row for row in visible if row["note_type"] == "Album note"]
    elif note_type == "Track notes":
        visible = [row for row in visible if row["note_type"] == "Track note"]

    if search:
        def matches_search(row):
            searchable = " ".join([
                row.get("display_name") or "",
                row.get("artist") or "",
                row.get("album") or "",
                row.get("track") or "",
                row.get("notes") or "",
            ]).lower()
            return search in searchable

        visible = [row for row in visible if matches_search(row)]

    album_ids = {
        row.get("album_id")
        for row in visible
        if row.get("album_id") is not None
    }
    album_note_count = sum(row["note_type"] == "Album note" for row in visible)
    track_note_count = sum(row["note_type"] == "Track note" for row in visible)

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Albums with notes", len(album_ids))
    metric2.metric("All notes", len(visible))
    metric3.metric("Album notes", album_note_count)
    metric4.metric("Track notes", track_note_count)

    if not visible:
        st.info("No notes match the current filters.")
        return

    grouped = {}
    for row in visible:
        album_id = row.get("album_id")
        group_key = album_id if album_id is not None else (
            row.get("artist"), row.get("album"), row.get("year")
        )
        if group_key not in grouped:
            grouped[group_key] = {
                "album_id": album_id,
                "artist": row.get("artist") or "Unknown artist",
                "album": row.get("album") or "Untitled",
                "year": row.get("year"),
                "artwork_url": row.get("artwork_url"),
                "notes": [],
            }
        grouped[group_key]["notes"].append(row)

    album_groups = list(grouped.values())

    for group in album_groups:
        group["notes"].sort(
            key=lambda row: (
                (row.get("display_name") or "").lower() if scope == "Everyone" else "",
                0 if row["note_type"] == "Album note" else 1,
                row.get("track_number") if row.get("track_number") is not None else 9999,
                (row.get("track") or "").lower(),
            )
        )
        timestamps = [
            row.get("updated_at") or row.get("created_at") or ""
            for row in group["notes"]
        ]
        group["latest_timestamp"] = max(timestamps) if timestamps else ""
        group["oldest_timestamp"] = min(timestamps) if timestamps else ""

    if sort_choice == "Recently updated":
        album_groups.sort(
            key=lambda group: group.get("latest_timestamp") or "",
            reverse=True,
        )
    elif sort_choice == "Oldest updated":
        album_groups.sort(
            key=lambda group: group.get("oldest_timestamp") or "",
        )
    else:
        album_groups.sort(key=lambda group: (
            (group.get("artist") or "").lower(),
            (group.get("album") or "").lower(),
        ))

    st.caption(
        f"{len(visible):,} notes across {len(album_groups):,} albums shown"
    )

    for group_index, group in enumerate(album_groups):
        with st.container(border=True):
            artwork_col, content_col, action_col = st.columns([1, 5, 1])

            with artwork_col:
                artwork_url = group.get("artwork_url")
                if artwork_url:
                    st.image(artwork_url, use_container_width=True)
                else:
                    with st.container(height=105, border=True):
                        st.write("")
                        st.markdown("### 🎵")

            with content_col:
                st.subheader(group["album"])
                metadata = [group["artist"]]
                if group.get("year"):
                    metadata.append(str(group["year"]))
                st.caption(" • ".join(metadata))

                # When viewing everyone, group the notes within an album by user.
                user_groups = {}
                for note_row in group["notes"]:
                    user_key = note_row.get("user_id") or note_row.get("display_name")
                    if user_key not in user_groups:
                        user_groups[user_key] = {
                            "display_name": note_row.get("display_name") or "User",
                            "rows": [],
                        }
                    user_groups[user_key]["rows"].append(note_row)

                user_sections = list(user_groups.values())
                user_sections.sort(key=lambda section: (
                    0 if any(
                        row.get("user_id") == st.session_state.user_id
                        for row in section["rows"]
                    ) else 1,
                    section["display_name"].lower(),
                ))

                for user_index, section in enumerate(user_sections):
                    if scope == "Everyone":
                        name = section["display_name"]
                        is_me = any(
                            row.get("user_id") == st.session_state.user_id
                            for row in section["rows"]
                        )
                        if is_me:
                            name = f"{name} (you)"
                        st.markdown(f"#### {name}")

                    album_note_rows = [
                        row for row in section["rows"]
                        if row["note_type"] == "Album note"
                    ]
                    track_note_rows = [
                        row for row in section["rows"]
                        if row["note_type"] == "Track note"
                    ]

                    if album_note_rows:
                        album_note = album_note_rows[0]
                        rating = album_note.get("rating")
                        label = "Album note"
                        if rating is not None:
                            label += f" • Rating: {rating}/5"
                        st.markdown(f"**{label}**")
                        st.write(album_note["notes"])

                    if album_note_rows and track_note_rows:
                        st.markdown("---")

                    if track_note_rows:
                        st.markdown(f"**Track notes ({len(track_note_rows)})**")
                        for track_row in track_note_rows:
                            track_label = track_row.get("track") or "Untitled track"
                            if track_row.get("track_number") is not None:
                                track_label = f"{track_row['track_number']}. {track_label}"
                            st.caption(track_label)
                            st.write(track_row["notes"])

                    if user_index < len(user_sections) - 1:
                        st.divider()

                latest = group.get("latest_timestamp")
                if latest:
                    try:
                        formatted = pd.to_datetime(latest).strftime("%b %d, %Y")
                    except Exception:
                        formatted = str(latest)
                    st.caption(f"Most recently updated: {formatted}")

            with action_col:
                album_id = group.get("album_id")
                if album_id and st.button(
                    "Open album",
                    key=f"notes_group_open_{group_index}_{album_id}",
                    use_container_width=True,
                ):
                    st.session_state.selected_album_id = album_id
                    st.rerun()


# ============================================================
# TOP RATED PAGE
# ============================================================

def top_rated_page():
    set_supabase_session()
    render_sidebar_identity()

    st.title("Top Rated")
    st.write(
        "See your highest-rated albums or the albums rated highest by the community."
    )

    try:
        ratings = get_all_album_ratings()
    except Exception as exc:
        st.error(f"Could not load album ratings: {exc}")
        return

    if not ratings:
        st.info("No album ratings have been saved yet.")
        return

    mode_col, min_col, limit_col = st.columns([1.5, 1, 1])

    with mode_col:
        rating_scope = st.selectbox(
            "Ratings",
            ["My ratings", "Community ratings"],
        )

    with min_col:
        if rating_scope == "Community ratings":
            max_ratings = max(
                1,
                max(
                    sum(1 for row in ratings if row.get("album_id") == album_id)
                    for album_id in {row.get("album_id") for row in ratings}
                ),
            )
            minimum_ratings = st.number_input(
                "Minimum ratings",
                min_value=1,
                max_value=max_ratings,
                value=1,
                step=1,
            )
        else:
            minimum_ratings = 1
            st.caption("Sorted by your rating")

    with limit_col:
        result_limit = st.selectbox(
            "Albums to show",
            [10, 25, 50, 100],
            index=1,
        )

    if rating_scope == "My ratings":
        display_rows = []
        for row in ratings:
            if row.get("user_id") != st.session_state.user_id:
                continue
            album = relation_one(row.get("albums"))
            artist_data = relation_one(album.get("artists"))
            display_rows.append({
                "album_id": row.get("album_id"),
                "artist": artist_data.get("name") or "Unknown artist",
                "album": album.get("title") or "Untitled",
                "year": album.get("year"),
                "artwork_url": album.get("artwork_url"),
                "rating": float(row.get("rating")),
                "rating_count": 1,
                "updated_at": row.get("updated_at") or "",
            })

        display_rows.sort(key=lambda row: (
            -row["rating"],
            (row.get("artist") or "").lower(),
            (row.get("album") or "").lower(),
        ))

        if not display_rows:
            st.info("You have not rated any albums yet.")
            return

        average = sum(row["rating"] for row in display_rows) / len(display_rows)
        metric1, metric2 = st.columns(2)
        metric1.metric("Albums you've rated", len(display_rows))
        metric2.metric("Your average rating", f"{average:.2f}/5")

    else:
        grouped = {}
        for row in ratings:
            album_id = row.get("album_id")
            if album_id is None:
                continue
            if album_id not in grouped:
                album = relation_one(row.get("albums"))
                artist_data = relation_one(album.get("artists"))
                grouped[album_id] = {
                    "album_id": album_id,
                    "artist": artist_data.get("name") or "Unknown artist",
                    "album": album.get("title") or "Untitled",
                    "year": album.get("year"),
                    "artwork_url": album.get("artwork_url"),
                    "ratings": [],
                    "my_rating": None,
                }
            numeric_rating = float(row.get("rating"))
            grouped[album_id]["ratings"].append(numeric_rating)
            if row.get("user_id") == st.session_state.user_id:
                grouped[album_id]["my_rating"] = numeric_rating

        display_rows = []
        for group in grouped.values():
            count = len(group["ratings"])
            if count < minimum_ratings:
                continue
            group["rating_count"] = count
            group["rating"] = sum(group["ratings"]) / count
            display_rows.append(group)

        display_rows.sort(key=lambda row: (
            -row["rating"],
            -row["rating_count"],
            (row.get("artist") or "").lower(),
            (row.get("album") or "").lower(),
        ))

        if not display_rows:
            st.info("No albums meet the selected minimum number of ratings.")
            return

        all_ratings = [float(row.get("rating")) for row in ratings]
        community_average = sum(all_ratings) / len(all_ratings)
        metric1, metric2, metric3 = st.columns(3)
        metric1.metric("Albums rated", len(grouped))
        metric2.metric("Ratings submitted", len(ratings))
        metric3.metric("Community average", f"{community_average:.2f}/5")

    display_rows = display_rows[:result_limit]
    st.caption(f"Showing {len(display_rows):,} albums")

    for rank, row in enumerate(display_rows, start=1):
        with st.container(border=True):
            artwork_col, content_col, action_col = st.columns([1, 5, 1])

            with artwork_col:
                if row.get("artwork_url"):
                    st.image(row["artwork_url"], use_container_width=True)
                else:
                    with st.container(height=105, border=True):
                        st.write("")
                        st.markdown("### 🎵")

            with content_col:
                st.subheader(f"#{rank} — {row['album']}")
                metadata = [row["artist"]]
                if row.get("year"):
                    metadata.append(str(row["year"]))
                st.caption(" • ".join(metadata))

                if rating_scope == "My ratings":
                    st.markdown(f"**Your rating: {row['rating']:g}/5**")
                else:
                    count = row["rating_count"]
                    rating_word = "rating" if count == 1 else "ratings"
                    st.markdown(
                        f"**Community rating: {row['rating']:.2f}/5** "
                        f"• {count} {rating_word}"
                    )
                    if row.get("my_rating") is not None:
                        st.caption(f"Your rating: {row['my_rating']:g}/5")

            with action_col:
                if st.button(
                    "Open album",
                    key=f"top_rated_open_{rating_scope}_{rank}_{row['album_id']}",
                    use_container_width=True,
                ):
                    st.session_state.selected_album_id = row["album_id"]
                    st.rerun()


# ============================================================
# LAST.FM PAGE
# ============================================================

def lastfm_page():
    set_supabase_session()
    render_sidebar_identity()

    st.title("Last.fm Audit")
    st.write(
        "Compare your most-played Last.fm albums with the albums "
        "currently in the Plex library."
    )

    profile = get_my_profile()
    saved_username = profile.get("lastfm_username") or ""

    with st.container(border=True):
        st.subheader("Last.fm account")
        with st.form("lastfm_username_form"):
            username = st.text_input(
                "Last.fm username",
                value=saved_username,
                help=(
                    "Only your public Last.fm username is stored. "
                    "Your Last.fm password is never requested."
                ),
            )
            save_username = st.form_submit_button("Save username")

        if save_username:
            try:
                save_lastfm_username(username.strip())
                st.success("Last.fm username saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save Last.fm username: {exc}")

    if not saved_username:
        st.info("Save your Last.fm username above to analyze your top albums.")
        return

    st.subheader("Top albums")
    period_labels = {
        "Last 7 days": "7day",
        "Last month": "1month",
        "Last 3 months": "3month",
        "Last 6 months": "6month",
        "Last 12 months": "12month",
        "Overall": "overall",
    }

    controls_left, controls_right = st.columns(2)
    with controls_left:
        period_label = st.selectbox(
            "Listening period", list(period_labels.keys()), index=2
        )
    with controls_right:
        limit = st.selectbox(
            "Albums to analyze", [25, 50, 100, 200], index=2
        )

    period = period_labels[period_label]
    results_key = (saved_username, period, limit)
    refresh = st.button("Refresh from Last.fm", type="primary")

    if refresh or st.session_state.lastfm_results_key != results_key:
        try:
            with st.spinner("Getting your top albums from Last.fm..."):
                lastfm_albums = fetch_lastfm_top_albums(
                    saved_username, period=period, limit=limit
                )
                plex_albums = get_all_albums()
                compared = compare_lastfm_to_plex(lastfm_albums, plex_albums)
            st.session_state.lastfm_results = compared
            st.session_state.lastfm_results_key = results_key
        except Exception as exc:
            st.error(f"Could not retrieve Last.fm data: {exc}")
            return

    compared = st.session_state.lastfm_results or []
    if not compared:
        st.info("Last.fm returned no top albums for this period.")
        return

    in_plex_count = sum(1 for row in compared if row["in_plex"])
    missing_count = len(compared) - in_plex_count
    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Top albums", len(compared))
    metric2.metric("In Plex", in_plex_count)
    metric3.metric("Missing from Plex", missing_count)

    status_filter = st.segmented_control(
        "Show",
        options=["All", "In Plex", "Missing from Plex"],
        default="All",
    )

    if status_filter == "In Plex":
        visible = [row for row in compared if row["in_plex"]]
    elif status_filter == "Missing from Plex":
        visible = [row for row in compared if not row["in_plex"]]
    else:
        visible = compared

    st.caption(
        f"{len(visible):,} albums shown • matching uses artist and album-title normalization"
    )

    if not visible:
        st.info("No albums match this view.")
        return

    for row in visible:
        with st.container(border=True):
            rank_col, info_col, status_col = st.columns([0.5, 4, 1.4])
            with rank_col:
                st.markdown(f"### #{row['rank']}")
            with info_col:
                st.markdown(f"**{row['album']}**")
                st.caption(f"{row['artist']} • {row['playcount']:,} plays")
            with status_col:
                if row["in_plex"]:
                    st.success("In Plex")
                    if row.get("match_method"):
                        st.caption(row["match_method"])
                    if st.button(
                        "Open album",
                        key=f"lastfm_open_{row['rank']}_{row['plex_album_id']}",
                        use_container_width=True,
                    ):
                        st.session_state.selected_album_id = row["plex_album_id"]
                        st.rerun()
                else:
                    st.warning("Missing")


# ============================================================
# TRACK NOTE UI
# ============================================================

def render_track_notes(track):
    track_id = track["track_id"]

    current_note = get_my_track_note(
        track_id
    )

    with st.form(
        f"track_note_form_{track_id}"
    ):
        notes = st.text_area(
            "Your track notes",
            value=current_note.get("notes") or "",
            key=f"track_note_text_{track_id}",
            height=120,
        )

        save_note = st.form_submit_button(
            "Save track note",
            use_container_width=True,
        )

    if save_note:
        try:
            (
                supabase
                .table("track_notes")
                .upsert(
                    {
                        "track_id":
                            track_id,

                        "user_id":
                            st.session_state.user_id,

                        "notes":
                            notes.strip() or None,
                    },
                    on_conflict=(
                        "track_id,user_id"
                    ),
                )
                .execute()
            )

            st.success(
                "Track note saved."
            )

            st.rerun()

        except Exception as exc:
            st.error(
                f"Could not save track note: {exc}"
            )

    community_notes = get_community_track_notes(
        track_id
    )

    if community_notes:
        st.markdown("**Community track notes**")

        for note in community_notes:
            profile = relation_one(
                note.get("profiles")
            )

            name = (
                profile.get("display_name")
                or "User"
            )

            note_text = note.get("notes")

            if note_text:
                st.markdown(
                    f"**{name}:** {note_text}"
                )


# ============================================================
# ALBUM DETAIL PAGE
# ============================================================

def album_detail(album_id):
    set_supabase_session()

    if st.button(
        "← Back to albums"
    ):
        st.session_state.selected_album_id = None
        st.rerun()

    album = get_album_detail(
        album_id
    )

    if not album:
        st.error(
            "Album not found."
        )
        return

    artist_data = relation_one(
        album.get("artists")
    )

    artist = (
        artist_data.get("name")
        or "Unknown artist"
    )

    header_left, header_right = st.columns(
        [1, 3]
    )

    with header_left:
        render_artwork(
            album.get("artwork_url")
        )

    with header_right:
        st.title(
            album.get("title")
            or "Untitled"
        )

        st.subheader(
            artist
        )

        metadata = []

        if album.get("year"):
            metadata.append(
                str(album["year"])
            )

        if album.get("studio"):
            metadata.append(
                album["studio"]
            )

        if metadata:
            st.caption(
                " • ".join(metadata)
            )

        if album.get("summary"):
            st.write(
                album["summary"]
            )

    st.divider()

    left, right = st.columns(
        [2, 1]
    )

    with left:
        st.header("Tracks")

        tracks = get_tracks(
            album_id
        )

        if not tracks:
            st.info(
                "No tracks found for this album."
            )

        else:
            for track in tracks:
                track_number = (
                    track.get("track_number")
                )

                title = (
                    track.get("title")
                    or "Untitled"
                )

                duration = (
                    track.get("duration_human")
                    or ""
                )

                if track_number is not None:
                    label = (
                        f"{track_number}. {title}"
                    )
                else:
                    label = title

                if duration:
                    label += f" — {duration}"

                with st.expander(label):
                    details = []

                    if track.get("audio_codec"):
                        details.append(
                            f"Codec: {track['audio_codec']}"
                        )

                    if track.get("bitrate"):
                        details.append(
                            f"Bitrate: {track['bitrate']}"
                        )

                    if details:
                        st.caption(
                            " • ".join(details)
                        )

                    render_track_notes(
                        track
                    )

    with right:
        st.header(
            "Your album review"
        )

        current = get_my_review(
            album_id
        )

        current_rating = (
            current.get("rating")
        )

        if current_rating is not None:
            default_rating = float(
                current_rating
            )
        else:
            default_rating = 3.0

        current_notes = (
            current.get("notes")
            or ""
        )

        with st.form(
            f"review_{album_id}"
        ):
            rating = st.slider(
                "Rating",
                min_value=0.0,
                max_value=5.0,
                value=default_rating,
                step=0.5,
            )

            notes = st.text_area(
                "Album notes",
                value=current_notes,
                height=180,
            )

            save = (
                st.form_submit_button(
                    "Save album review",
                    use_container_width=True,
                )
            )

        if save:
            try:
                (
                    supabase
                    .table(
                        "album_reviews"
                    )
                    .upsert(
                        {
                            "album_id":
                                album_id,

                            "user_id":
                                st.session_state.user_id,

                            "rating":
                                rating,

                            "notes":
                                (
                                    notes.strip()
                                    or None
                                ),
                        },
                        on_conflict=(
                            "album_id,user_id"
                        ),
                    )
                    .execute()
                )

                st.success(
                    "Album review saved."
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    "Could not save "
                    f"album review: {exc}"
                )

    st.divider()

    st.header(
        "Community album reviews"
    )

    reviews = get_community_reviews(
        album_id
    )

    if not reviews:
        st.caption(
            "No album reviews yet."
        )

    else:
        for review in reviews:
            profile = relation_one(
                review.get("profiles")
            )

            name = (
                profile.get(
                    "display_name"
                )
                or "User"
            )

            rating = review.get(
                "rating"
            )

            notes = review.get(
                "notes"
            )

            with st.container(
                border=True
            ):
                if rating is not None:
                    st.markdown(
                        f"**{name} — "
                        f"{rating}/5**"
                    )
                else:
                    st.markdown(
                        f"**{name}**"
                    )

                if notes:
                    st.write(
                        notes
                    )


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

ensure_session()


if not st.session_state.user_id:
    login_page()

else:
    set_supabase_session()

    if st.session_state.selected_album_id:
        album_detail(
            st.session_state.selected_album_id
        )

    elif st.session_state.app_page == "Notes":
        notes_page()

    elif st.session_state.app_page == "Top Rated":
        top_rated_page()

    elif st.session_state.app_page == "Last.fm Audit":
        lastfm_page()

    else:
        album_browser()
