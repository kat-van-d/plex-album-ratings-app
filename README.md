# Plex Album Ratings — Streamlit v1

Features:
- Email/password sign-in and sign-up
- Browse albums
- Search by album or artist
- Filter by year
- Show only unrated albums for the current user
- Album detail view
- Track listing
- Per-user 0–5 rating in 0.5 increments
- Per-user notes
- Community reviews

Entrypoint: streamlit_app.py

In Streamlit Community Cloud > App settings > Secrets, add:

SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_ANON_KEY = "YOUR_PUBLISHABLE_OR_ANON_KEY"

Use the publishable/anon key here, NOT the secret/service-role key used by Cloud Run.
