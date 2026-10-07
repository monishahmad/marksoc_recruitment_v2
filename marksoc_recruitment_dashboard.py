import hashlib
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="MarkSoc JMI — Recruitment Review v2",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

TEAMS = [
    "Photography & Videography Team",
    "Content Team",
    "Editorial Team",
    "Graphics Team",
    "Sponsorship Team",
    "Event Management Team",
    "HR Team",
    "Brand Consulting Team",
    "Client Relations Team",
    "Marketing Team",
]

PREFERENCES = ["First Preference", "Second Preference", "Either"]
REVIEW_STATUSES = ["Not Reviewed", "Shortlist", "Maybe", "Reject"]
DEFAULT_CSV = Path(__file__).with_name("recruitment_responses.csv")
DB_PATH = Path(__file__).with_name("marksoc_reviews.db")

PERSONAL_ALIASES = {
    "timestamp": ["Timestamp"],
    "name": ["Name"],
    "contact": ["Contact Number"],
    "email": ["Email Address", "Email Address  "],
    "course": ["Course & Year"],
    "student_id": ["Student ID"],
    "cv": ["CV /Resume", "CV /Resume "],
}


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_header(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def resolve_column(df, aliases):
    normalized = {normalize_header(c): c for c in df.columns}
    for alias in aliases:
        if alias in df.columns:
            return alias
        if normalize_header(alias) in normalized:
            return normalized[normalize_header(alias)]
    return None


def load_data(uploaded_file=None):
    if uploaded_file is not None:
        return pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
    if not DEFAULT_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(DEFAULT_CSV, dtype=str, keep_default_na=False)


def find_team_columns(df):
    candidates = [
        c for c in df.columns
        if "which team would you like to apply for?" in normalize_header(c).lower()
    ]
    # Google Forms normally creates the second duplicate with a .1 suffix.
    # Do not depend on that exact suffix; preserve column order instead.
    if len(candidates) >= 2:
        return candidates[0], candidates[1]
    if len(candidates) == 1:
        return candidates[0], None
    return None, None


def get_personal_columns(df):
    return {
        key: resolve_column(df, aliases)
        for key, aliases in PERSONAL_ALIASES.items()
    }


def response_columns(df, first_col, second_col, personal_cols):
    excluded = {c for c in personal_cols.values() if c}
    excluded.update(c for c in [first_col, second_col] if c)
    return [c for c in df.columns if c not in excluded]


def applicant_matches(row, team, preference, first_col, second_col):
    first = clean_text(row.get(first_col, "")) if first_col else ""
    second = clean_text(row.get(second_col, "")) if second_col else ""
    if preference == "First Preference":
        return first == team
    if preference == "Second Preference":
        return second == team
    return first == team or second == team


def make_applicant_id(row, personal_cols):
    timestamp = clean_text(row.get(personal_cols.get("timestamp"), "")) if personal_cols.get("timestamp") else ""
    name = clean_text(row.get(personal_cols.get("name"), "")) if personal_cols.get("name") else ""
    email = clean_text(row.get(personal_cols.get("email"), "")) if personal_cols.get("email") else ""
    student_id = clean_text(row.get(personal_cols.get("student_id"), "")) if personal_cols.get("student_id") else ""
    raw = "|".join([timestamp, name, email, student_id])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                applicant_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'Not Reviewed',
                score INTEGER NOT NULL DEFAULT 0,
                comments TEXT NOT NULL DEFAULT '',
                reviewer_team TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.commit()


def get_review(applicant_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT status, score, comments, reviewer_team, updated_at FROM reviews WHERE applicant_id = ?",
            (applicant_id,),
        ).fetchone()
    if not row:
        return {"status": "Not Reviewed", "score": 0, "comments": "", "reviewer_team": "", "updated_at": ""}
    return {
        "status": row[0],
        "score": row[1],
        "comments": row[2],
        "reviewer_team": row[3],
        "updated_at": row[4],
    }


def save_review(applicant_id, status, score, comments, reviewer_team):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO reviews (applicant_id, status, score, comments, reviewer_team, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(applicant_id) DO UPDATE SET
                status=excluded.status,
                score=excluded.score,
                comments=excluded.comments,
                reviewer_team=excluded.reviewer_team,
                updated_at=excluded.updated_at
            """,
            (applicant_id, status, int(score), comments, reviewer_team, now),
        )
        conn.commit()


def get_all_reviews():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT applicant_id, status, score, comments, reviewer_team, updated_at FROM reviews"
        ).fetchall()
    return {
        r[0]: {
            "status": r[1],
            "score": r[2],
            "comments": r[3],
            "reviewer_team": r[4],
            "updated_at": r[5],
        }
        for r in rows
    }


def get_access_codes():
    """Read team access codes from MARKSOC_TEAM_CODES.

    Format:
    Team Name=code||Another Team=code

    If not configured, the app remains usable in open local-review mode.
    """
    raw = os.getenv("MARKSOC_TEAM_CODES", "").strip()
    codes = {}
    if not raw:
        return codes
    for item in raw.split("||"):
        if "=" not in item:
            continue
        team, code = item.split("=", 1)
        team, code = team.strip(), code.strip()
        if team in TEAMS and code:
            codes[team] = code
    return codes


def check_access(team, supplied_code):
    codes = get_access_codes()
    if not codes:
        return True
    expected = codes.get(team)
    if not expected:
        return False
    return supplied_code == expected


def format_timestamp(value):
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return clean_text(value)
        return parsed.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return clean_text(value)


init_db()

st.markdown(
    "<div class='main-title'>📋 MarkSoc JMI — Recruitment Review <span class='v2'>v2</span></div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='subtle'>Team-based applicant review with robust Google Forms import, persistent decisions, scoring and comments.</div>",
    unsafe_allow_html=True,
)

st.markdown(
    """
<style>
.main-title { font-size: 2.05rem; font-weight: 800; margin-bottom: .15rem; }
.v2 { font-size: .8rem; vertical-align: middle; padding: .18rem .45rem; border-radius: 999px; background: rgba(128,128,128,.15); }
.subtle { color: #6b7280; margin-bottom: 1rem; }
.answer { padding: .85rem 1rem; border-left: 3px solid #888; background: rgba(128,128,128,.06); border-radius: 5px; white-space: pre-wrap; }
.review-box { padding: .75rem 1rem; border: 1px solid rgba(128,128,128,.25); border-radius: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Recruitment Controls")
    uploaded = st.file_uploader(
        "Upload latest Google Forms CSV",
        type=["csv"],
        help="Google Forms → Responses → Download responses → CSV.",
    )

    if st.button("🔄 Reload current data", use_container_width=True):
        st.rerun()

    st.divider()
    st.subheader("Team Head View")
    team = st.selectbox("Select team", TEAMS)

    access_codes = get_access_codes()
    if access_codes:
        team_code = st.text_input("Team access code", type="password")
        if not check_access(team, team_code):
            st.warning("Enter the correct access code for this team.")
            st.stop()
    else:
        st.caption("Open local mode: set MARKSOC_TEAM_CODES to enable team-specific access codes.")

    preference = st.radio("Applicant preference", PREFERENCES, index=0)
    search = st.text_input("Search applicant", placeholder="Name, email, student ID...")
    sort_by = st.selectbox("Sort applicants by", ["Name (A–Z)", "Latest application", "Course & Year", "Review score"])

    st.divider()
    st.subheader("Review filter")
    status_filter = st.multiselect("Show statuses", REVIEW_STATUSES, default=REVIEW_STATUSES)

    st.divider()
    st.caption("Review data is stored locally in marksoc_reviews.db. Do not share the database or CSV publicly; they contain applicant information.")

df = load_data(uploaded)
if df.empty:
    st.warning("No recruitment CSV is loaded. Upload the Google Forms CSV from the sidebar.")
    st.stop()

first_col, second_col = find_team_columns(df)
if not first_col:
    st.error("Could not identify the team-preference column. This CSV does not appear to match the MarkSoc recruitment form structure.")
    st.stop()

personal_cols = get_personal_columns(df)
name_col = personal_cols.get("name")
if not name_col:
    st.error("Could not identify the applicant Name column.")
    st.stop()

# Stable ID for every application, including duplicate names.
df = df.copy()
df["_applicant_id"] = df.apply(lambda r: make_applicant_id(r, personal_cols), axis=1)

reviews = get_all_reviews()
df["_review_status"] = df["_applicant_id"].map(lambda x: reviews.get(x, {}).get("status", "Not Reviewed"))
df["_review_score"] = df["_applicant_id"].map(lambda x: reviews.get(x, {}).get("score", 0))

mask = df.apply(lambda row: applicant_matches(row, team, preference, first_col, second_col), axis=1)
filtered = df.loc[mask].copy()

if search:
    q = search.strip().lower()
    searchable_cols = [c for c in [name_col, personal_cols.get("email"), personal_cols.get("student_id"), personal_cols.get("course"), personal_cols.get("contact")] if c]
    search_mask = filtered[searchable_cols].fillna("").astype(str).apply(
        lambda col: col.str.lower().str.contains(q, regex=False)
    ).any(axis=1)
    filtered = filtered.loc[search_mask]

if status_filter:
    filtered = filtered[filtered["_review_status"].isin(status_filter)]
else:
    filtered = filtered.iloc[0:0]

if sort_by == "Name (A–Z)":
    filtered = filtered.sort_values(name_col, key=lambda s: s.fillna("").str.lower())
elif sort_by == "Latest application":
    ts_col = personal_cols.get("timestamp")
    if ts_col:
        filtered["_sort_timestamp"] = pd.to_datetime(filtered[ts_col], errors="coerce")
        filtered = filtered.sort_values("_sort_timestamp", ascending=False).drop(columns=["_sort_timestamp"])
elif sort_by == "Course & Year" and personal_cols.get("course"):
    filtered = filtered.sort_values(personal_cols["course"], key=lambda s: s.fillna("").str.lower())
elif sort_by == "Review score":
    filtered = filtered.sort_values(["_review_score", name_col], ascending=[False, True])

c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.metric("Applicants shown", len(filtered))
with c2: st.metric("Total applications", len(df))
with c3: st.metric("1st preference", int((df[first_col].astype(str).str.strip() == team).sum()))
with c4: st.metric("2nd preference", int((df[second_col].astype(str).str.strip() == team).sum()) if second_col else 0)
with c5: st.metric("Shortlisted", int((filtered["_review_status"] == "Shortlist").sum()))

st.subheader(f"{team} · {preference}")
if filtered.empty:
    st.info("No applicants match the selected team, preference, search and review filters.")
    st.stop()

# Applicant table
email_col = personal_cols.get("email")
course_col = personal_cols.get("course")
student_col = personal_cols.get("student_id")

display_cols = [c for c in [name_col, course_col, student_col, email_col, first_col, second_col] if c]
table = filtered[display_cols + ["_review_status", "_review_score"]].copy()
rename = {name_col: "Name", "_review_status": "Review Status", "_review_score": "Score"}
if course_col: rename[course_col] = "Course & Year"
if student_col: rename[student_col] = "Student ID"
if email_col: rename[email_col] = "Email"
rename[first_col] = "1st Preference"
if second_col: rename[second_col] = "2nd Preference"
table = table.rename(columns=rename)
st.dataframe(table, use_container_width=True, hide_index=True, height=min(560, 100 + 38 * len(table)))

# Stable selector labels include student ID/email so duplicate names are unambiguous.
def selector_label(idx, row):
    name = clean_text(row.get(name_col, "")) or "Unnamed applicant"
    sid = clean_text(row.get(student_col, "")) if student_col else ""
    email = clean_text(row.get(email_col, "")) if email_col else ""
    identifier = sid or email or clean_text(row.get("_applicant_id", ""))[:8]
    return f"{idx:02d} — {name} · {identifier}"

options = [selector_label(i + 1, row) for i, (_, row) in enumerate(filtered.iterrows())]
selected = st.selectbox("Open applicant", options)
selected_pos = options.index(selected)
applicant = filtered.iloc[selected_pos]
applicant_id = applicant["_applicant_id"]

st.divider()
name = clean_text(applicant.get(name_col, "")) or "Unnamed applicant"
st.header(name)

# Review panel
review = get_review(applicant_id)
st.subheader("Recruitment Review")
with st.form(f"review_form_{applicant_id}"):
    rc1, rc2 = st.columns([1, 1])
    with rc1:
        new_status = st.selectbox("Decision", REVIEW_STATUSES, index=REVIEW_STATUSES.index(review["status"]))
    with rc2:
        new_score = st.slider("Score", min_value=0, max_value=100, value=int(review["score"]), step=1)
    new_comments = st.text_area("Team-head comments", value=review["comments"], height=120, placeholder="Interview notes, strengths, concerns, follow-up...")
    submitted = st.form_submit_button("💾 Save review", type="primary", use_container_width=True)
    if submitted:
        save_review(applicant_id, new_status, new_score, new_comments, team)
        st.success("Review saved.")
        st.rerun()

if review["updated_at"]:
    st.caption(f"Last saved: {review['updated_at']} · Reviewer team: {review['reviewer_team'] or '—'}")

# Personal information
st.subheader("Applicant Information")
info_items = [
    ("Course & Year", applicant.get(course_col, "") if course_col else ""),
    ("Student ID", applicant.get(student_col, "") if student_col else ""),
    ("Email", applicant.get(email_col, "") if email_col else ""),
    ("Contact", applicant.get(personal_cols.get("contact"), "") if personal_cols.get("contact") else ""),
    ("Application time", format_timestamp(applicant.get(personal_cols.get("timestamp"), "")) if personal_cols.get("timestamp") else ""),
]
info_cols = st.columns(5)
for col, (label, value) in zip(info_cols, info_items):
    with col:
        st.markdown(f"**{label}**")
        st.write(clean_text(value) or "—")

cv = clean_text(applicant.get(personal_cols.get("cv"), "")) if personal_cols.get("cv") else ""
if cv:
    # Google Forms can return multiple file links separated by commas/newlines.
    links = [x.strip() for x in re.split(r"[\n,]+", cv) if x.strip()]
    st.markdown("**CV / Resume:**")
    for n, link in enumerate(links, 1):
        st.markdown(f"[{('Open CV / Resume' if len(links) == 1 else f'Open file {n}')} ]({link})")

st.markdown(
    f"**1st Preference:** `{clean_text(applicant.get(first_col, '')) or '—'}`  \n"
    f"**2nd Preference:** `{clean_text(applicant.get(second_col, '')) if second_col else '—'}`"
)

st.subheader("Submitted Responses")
answer_cols = response_columns(df, first_col, second_col, personal_cols)
shown_answers = 0
for question in answer_cols:
    answer = clean_text(applicant.get(question, ""))
    if not answer:
        continue
    label = normalize_header(question)
    with st.expander(label, expanded=False):
        st.markdown(f'<div class="answer">{answer}</div>', unsafe_allow_html=True)
    shown_answers += 1
if shown_answers == 0:
    st.info("No non-empty question responses were found for this applicant.")

# Exports
st.divider()
export_df = filtered.drop(columns=["_applicant_id"], errors="ignore").copy()
export_df = export_df.drop(columns=["_review_status", "_review_score"], errors="ignore")
st.download_button(
    "⬇️ Download filtered applicants as CSV",
    data=export_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"MarkSoc_{quote(team.replace(' ', '_'))}_{preference.replace(' ', '_')}.csv",
    mime="text/csv",
)

# Review export for the selected team.
review_export = filtered[["_applicant_id", name_col]].copy()
review_export["Review Status"] = filtered["_applicant_id"].map(lambda x: reviews.get(x, {}).get("status", "Not Reviewed"))
review_export["Score"] = filtered["_applicant_id"].map(lambda x: reviews.get(x, {}).get("score", 0))
review_export["Comments"] = filtered["_applicant_id"].map(lambda x: reviews.get(x, {}).get("comments", ""))
review_export = review_export.rename(columns={"_applicant_id": "Applicant ID", name_col: "Name"})
st.download_button(
    "⬇️ Download review tracker",
    data=review_export.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"MarkSoc_{team.replace(' ', '_')}_Review_Tracker.csv",
    mime="text/csv",
)

st.caption(f"Loaded {len(df)} applications. Showing {len(filtered)} matching applicants. Review database: {DB_PATH.name}")
