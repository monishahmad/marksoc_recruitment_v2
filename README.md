# MarkSoc JMI — Recruitment Review Dashboard v2

A local Streamlit dashboard for reviewing the 2026–27 MarkSoc JMI recruitment Google Forms export.

## What v2 adds

- Robust detection of first and second team-preference columns, including future Google Forms `.1`-style changes.
- Duplicate-safe applicant selection using Student ID/email/application identity.
- Proper timestamp parsing for latest-application sorting.
- Team-head access-code support through an environment variable.
- Persistent review database using SQLite (`marksoc_reviews.db`).
- Review decisions: **Not Reviewed / Shortlist / Maybe / Reject**.
- Applicant score from **0–100**.
- Team-head comments and review timestamps.
- Review-status filtering.
- Review-score sorting.
- Full submitted question responses.
- CV/Resume links.
- Filtered applicant CSV export.
- Review tracker CSV export.

## 1. Install

Open Command Prompt / PowerShell in this folder:

```bash
pip install -r requirements.txt
```

## 2. Run

```bash
streamlit run marksoc_recruitment_dashboard.py
```

The browser should open automatically. If not, Streamlit will show the local URL in the terminal.

## 3. Data

The bundled `recruitment_responses.csv` is used automatically.

For a newer Google Forms export, use **Upload latest Google Forms CSV** in the sidebar.

The app does not modify the original CSV.

## 4. Team-head access codes (recommended)

By default, v2 is in **open local mode**. For actual team-head use, configure team-specific access codes before starting Streamlit.

### Windows PowerShell

```powershell
$env:MARKSOC_TEAM_CODES='Marketing Team=MARKETING123||HR Team=HR123||Event Management Team=EVENT123'
streamlit run marksoc_recruitment_dashboard.py
```

### Windows Command Prompt

```cmd
set MARKSOC_TEAM_CODES=Marketing Team=MARKETING123||HR Team=HR123||Event Management Team=EVENT123
streamlit run marksoc_recruitment_dashboard.py
```

Add every team you want to protect using the same format:

```text
Team Name=accesscode||Another Team=accesscode
```

**Do not put real passwords in the source code or GitHub.**

## 5. Review workflow

1. Select the team.
2. Enter that team's access code if enabled.
3. Choose First Preference, Second Preference, or Either.
4. Search/filter applicants.
5. Open an applicant.
6. Read the complete submitted responses.
7. Assign a score and decision.
8. Add comments.
9. Click **Save review**.
10. Export the filtered applicants or review tracker when required.

Reviews are stored in `marksoc_reviews.db` beside the Python file.

## Important privacy note

The CSV contains applicant names, contact numbers, email addresses, student IDs and submitted files/links. Keep the CSV, SQLite database and dashboard restricted to authorized recruitment members. Do not commit them to a public GitHub repository.

## Requirements

- Python 3.9+
- Streamlit
- pandas
