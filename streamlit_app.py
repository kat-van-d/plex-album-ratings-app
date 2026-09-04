import streamlit as st
from supabase import create_client, Client
import pandas as pd

st.set_page_config(page_title="Plex Album Ratings", page_icon="🎵", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def init_state():
    defaults = {
        "access_token": None,
        "refresh_token": None,
        "user_id": None,
        "user_email": None,
        "display_name": None,
        "selected_album_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def restore_session():
    if st.session_state.access_token and st.session_state.refresh_token:
        supabase.auth.set_session(
            st.session_state.access_token,
            st.session_state.refresh_token,
        )


def sign_out():
    try:
        restore_session()
        supabase.auth.sign_out()
    except Exception:
        pass
    for k in ["access_token", "refresh_token", "user_id", "user_email", "display_name", "selected_album_id"]:
        st.session_state[k] = None
    st.rerun()


def login_screen():
    st.title("🎵 Plex Album Ratings")
    st.write("Sign in to browse the library and save your ratings and notes.")
    login_tab, signup_tab = st.tabs(["Sign in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign in", use_container_width=True)
        if submit:
            try:
                response = supabase.auth.sign_in_with_password({"email": email.strip(), "password": password})
                st.session_state.access_token = response.session.access_token
                st.session_state.refresh_token = response.session.refresh_token
                st.session_state.user_id = response.user.id
                st.session_state.user_email = response.user.email
                restore_session()
                profile = (
                    supabase.table("profiles")
                    .select("display_name")
                    .eq("user_id", response.user.id)
                    .maybe_single()
                    .execute()
                )
                if profile.data:
                    st.session_state.display_name = profile.data.get("display_name")
                st.rerun()
            except Exception as exc:
                st.error(f"Sign in failed: {exc}")

    with signup_tab:
        with st.form("signup_form"):
            display_name = st.text_input("Display name")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            submit = st.form_submit_button("Create account", use_container_width=True)
        if submit:
            try:
                response = supabase.auth.sign_up({
                    "email": email.strip(),
                    "password": password,
                    "options": {"data": {"display_name": display_name.strip()}},
                })
                if response.session:
                    st.session_state.access_token = response.session.access_token
                    st.session_state.refresh_token = response.session.refresh_token
                    st.session_state.user_id = response.user.id
                    st.session_state.user_email = response.user.email
                    st.session_state.display_name = display_name.strip()
                    st.rerun()
                else:
                    st.success("Account created. Check your email for the confirmation link, then return and sign in.")
            except Exception as exc:
                st.error(f"Account creation failed: {exc}")


def sidebar_controls():
    with st.sidebar:
        st.header("Music Library")
        st.caption(f"Signed in as {st.session_state.display_name or st.session_state.user_email}")
        if st.button("Sign out", use_container_width=True):
            sign_out()
        st.divider()
        search = st.text_input("Search albums or artists")
        year_response = (
            supabase.table("albums")
            .select("year")
            .not_.is_("year", "null")
            .order("year")
            .execute()
        )
        years = sorted({r["year"] for r in (year_response.data or []) if r.get("year") is not None})
        year_choice = st.selectbox("Year", ["All"] + [str(y) for y in years])
        sort_choice = st.selectbox("Sort", ["Artist / Album", "Album title", "Year (newest)", "Year (oldest)"])
        only_unrated = st.checkbox("Only albums I haven't rated")
    return search.strip(), year_choice, sort_choice, only_unrated


def my_reviews():
    response = (
        supabase.table("album_reviews")
        .select("album_id,rating,notes")
        .eq("user_id", st.session_state.user_id)
        .execute()
    )
    return response.data or []


def album_rows(search, year_choice, sort_choice):
    query = supabase.table("albums").select(
        "album_id,title,year,studio,summary,thumb,art,artist_id,artists(name)"
    ).limit(1000)
    if year_choice != "All":
        query = query.eq("year", int(year_choice))
    rows = query.execute().data or []

    if search:
        q = search.lower()
        rows = [r for r in rows if q in (r.get("title") or "").lower() or q in ((r.get("artists") or {}).get("name") or "").lower()]

    if sort_choice == "Artist / Album":
        rows.sort(key=lambda r: (((r.get("artists") or {}).get("name") or "").lower(), (r.get("title") or "").lower()))
    elif sort_choice == "Album title":
        rows.sort(key=lambda r: (r.get("title") or "").lower())
    elif sort_choice == "Year (newest)":
        rows.sort(key=lambda r: r.get("year") or 0, reverse=True)
    else:
        rows.sort(key=lambda r: r.get("year") or 9999)
    return rows


def browser_page():
    search, year_choice, sort_choice, only_unrated = sidebar_controls()
    st.title("Albums")
    reviewed = {r["album_id"]: r for r in my_reviews()}
    rows = album_rows(search, year_choice, sort_choice)
    if only_unrated:
        rows = [r for r in rows if r["album_id"] not in reviewed]
    st.caption(f"{len(rows):,} albums shown")

    for row in rows:
        artist = (row.get("artists") or {}).get("name") or "Unknown artist"
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.subheader(row.get("title") or "Untitled")
                meta = artist + (f" • {row['year']}" if row.get("year") else "")
                st.write(meta)
                review = reviewed.get(row["album_id"])
                st.caption(f"Your rating: {review['rating']}/5" if review and review.get("rating") is not None else "Not yet rated")
            with right:
                if st.button("Open", key=f"open_{row['album_id']}", use_container_width=True):
                    st.session_state.selected_album_id = row["album_id"]
                    st.rerun()


def album_detail(album_id):
    if st.button("← Back to albums"):
        st.session_state.selected_album_id = None
        st.rerun()

    album = (
        supabase.table("albums")
        .select("album_id,title,year,studio,summary,rating,plex_user_rating,artist_id,artists(name)")
        .eq("album_id", album_id)
        .single()
        .execute()
        .data
    )
    artist = (album.get("artists") or {}).get("name") or "Unknown artist"
    st.title(album.get("title") or "Untitled")
    st.subheader(artist)
    meta = [str(album["year"])] if album.get("year") else []
    if album.get("studio"):
        meta.append(album["studio"])
    if meta:
        st.caption(" • ".join(meta))
    if album.get("summary"):
        st.write(album["summary"])

    left, right = st.columns([2, 1])
    with left:
        st.header("Tracks")
        tracks = (
            supabase.table("tracks")
            .select("track_number,title,duration_human,audio_codec,bitrate")
            .eq("album_id", album_id)
            .order("track_number")
            .execute()
            .data or []
        )
        st.dataframe(pd.DataFrame(tracks), hide_index=True, use_container_width=True)

    with right:
        st.header("Your review")
        current = (
            supabase.table("album_reviews")
            .select("review_id,rating,notes")
            .eq("album_id", album_id)
            .eq("user_id", st.session_state.user_id)
            .maybe_single()
            .execute()
            .data
        ) or {}
        with st.form(f"review_{album_id}"):
            rating = st.slider("Rating", 0.0, 5.0, float(current.get("rating") if current.get("rating") is not None else 3.0), 0.5)
            notes = st.text_area("Notes", value=current.get("notes") or "", height=180)
            save = st.form_submit_button("Save review", use_container_width=True)
        if save:
            try:
                supabase.table("album_reviews").upsert({
                    "album_id": album_id,
                    "user_id": st.session_state.user_id,
                    "rating": rating,
                    "notes": notes.strip() or None,
                }, on_conflict="album_id,user_id").execute()
                st.success("Review saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save review: {exc}")

    st.divider()
    st.header("Community reviews")
    reviews = (
        supabase.table("album_reviews")
        .select("rating,notes,user_id,profiles(display_name)")
        .eq("album_id", album_id)
        .execute()
        .data or []
    )
    if not reviews:
        st.caption("No reviews yet.")
    for review in reviews:
        name = (review.get("profiles") or {}).get("display_name") or "User"
        with st.container(border=True):
            st.markdown(f"**{name} — {review.get('rating')}/5**" if review.get("rating") is not None else f"**{name}**")
            if review.get("notes"):
                st.write(review["notes"])


init_state()
if not st.session_state.user_id:
    login_screen()
else:
    restore_session()
    if st.session_state.selected_album_id:
        album_detail(st.session_state.selected_album_id)
    else:
        browser_page()
