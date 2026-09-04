import streamlit as st
from supabase import create_client, Client
import pandas as pd


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
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def set_supabase_session():
    """
    Restore the authenticated Supabase session after a Streamlit rerun.
    """

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
# RELATIONSHIP HELPERS
# ============================================================

def relation_one(value):
    """
    Supabase/PostgREST normally returns a many-to-one relationship as
    a dict, but this helper also tolerates a one-item list.
    """

    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        if len(value) > 0:
            return value[0]

    return {}


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

    # --------------------------------------------------------
    # SIGN IN
    # --------------------------------------------------------

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

                # Avoid maybe_single().
                profile_response = (
                    supabase
                    .table("profiles")
                    .select("display_name")
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

    # --------------------------------------------------------
    # CREATE ACCOUNT
    # --------------------------------------------------------

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

                # If email confirmation is disabled,
                # Supabase may return a session immediately.
                if response.session:

                    st.session_state.access_token = (
                        response.session.access_token
                    )

                    st.session_state.refresh_token = (
                        response.session.refresh_token
                    )

                    st.session_state.user_id = response.user.id
                    st.session_state.user_email = response.user.email

                    st.session_state.display_name = (
                        display_name.strip()
                    )

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
    """
    Retrieve the full album library in pages.

    Supabase/PostgREST commonly limits a response to 1000 rows,
    so this fetches multiple ranges.
    """

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
                "thumb,"
                "art,"
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
            "thumb,"
            "art,"
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
    """
    Return the current user's review.

    Important:
    This deliberately uses limit(1) rather than maybe_single().
    """

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


# ============================================================
# SIDEBAR
# ============================================================

def sidebar_filters(albums):

    with st.sidebar:

        st.header("Music Library")

        user_label = (
            st.session_state.display_name
            or st.session_state.user_email
            or "Signed-in user"
        )

        st.caption(
            f"Signed in as {user_label}"
        )

        if st.button(
            "Sign out",
            use_container_width=True,
        ):
            sign_out()

        st.divider()

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

    return (
        search.strip(),
        year_choice,
        sort_choice,
        only_unrated,
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
    ) = sidebar_filters(albums)

    st.title("Albums")

    # --------------------------------------------------------
    # CURRENT USER'S REVIEWS
    # --------------------------------------------------------

    reviews = get_user_reviews()

    reviewed_by_album = {
        review["album_id"]: review
        for review in reviews
    }

    rows = albums.copy()

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

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
                search_lower
                in album_title.lower()
                or search_lower
                in artist_name.lower()
            ):
                filtered_rows.append(row)

        rows = filtered_rows

    # --------------------------------------------------------
    # YEAR FILTER
    # --------------------------------------------------------

    if year_choice != "All":

        selected_year = int(
            year_choice
        )

        rows = [
            row
            for row in rows
            if row.get("year") == selected_year
        ]

    # --------------------------------------------------------
    # UNRATED FILTER
    # --------------------------------------------------------

    if only_unrated:

        rows = [
            row
            for row in rows
            if row["album_id"]
            not in reviewed_by_album
        ]

    # --------------------------------------------------------
    # SORTING
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # DISPLAY ALBUMS
    # --------------------------------------------------------

    for row in rows:

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

        with st.container(
            border=True
        ):

            left, right = st.columns(
                [5, 1]
            )

            with left:

                st.subheader(title)

                detail = artist

                if year:
                    detail += f" • {year}"

                st.write(detail)

                if (
                    review
                    and review.get("rating")
                    is not None
                ):

                    st.caption(
                        f"Your rating: "
                        f"{review['rating']}/5"
                    )

                else:

                    st.caption(
                        "Not yet rated"
                    )

            with right:

                if st.button(
                    "Open",
                    key=(
                        f"open_"
                        f"{row['album_id']}"
                    ),
                    use_container_width=True,
                ):

                    st.session_state.selected_album_id = (
                        row["album_id"]
                    )

                    st.rerun()


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

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # TRACKS + REVIEW
    # --------------------------------------------------------

    left, right = st.columns(
        [2, 1]
    )

    # --------------------------------------------------------
    # TRACK LIST
    # --------------------------------------------------------

    with left:

        st.header("Tracks")

        tracks = get_tracks(
            album_id
        )

        if tracks:

            track_df = pd.DataFrame(
                tracks
            )

            display_columns = [
                column
                for column in [
                    "track_number",
                    "title",
                    "duration_human",
                    "audio_codec",
                    "bitrate",
                ]
                if column
                in track_df.columns
            ]

            track_df = track_df[
                display_columns
            ]

            track_df = track_df.rename(
                columns={
                    "track_number":
                        "#",
                    "title":
                        "Track",
                    "duration_human":
                        "Duration",
                    "audio_codec":
                        "Codec",
                    "bitrate":
                        "Bitrate",
                }
            )

            st.dataframe(
                track_df,
                hide_index=True,
                use_container_width=True,
            )

        else:

            st.info(
                "No tracks found "
                "for this album."
            )

    # --------------------------------------------------------
    # USER REVIEW
    # --------------------------------------------------------

    with right:

        st.header(
            "Your review"
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
                "Notes",
                value=current_notes,
                height=180,
            )

            save = (
                st.form_submit_button(
                    "Save review",
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
                    "Review saved."
                )

                st.rerun()

            except Exception as exc:

                st.error(
                    "Could not save "
                    f"review: {exc}"
                )

    # --------------------------------------------------------
    # COMMUNITY REVIEWS
    # --------------------------------------------------------

    st.divider()

    st.header(
        "Community reviews"
    )

    reviews = get_community_reviews(
        album_id
    )

    if not reviews:

        st.caption(
            "No reviews yet."
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

    else:

        album_browser()
