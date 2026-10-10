# MiTiN language-pair directory

A Wild Apricot Custom HTML gadget that searches members by translation and
interpreting language pair, plus the pipeline that keeps its data current.

## Why there is a pipeline at all

Wild Apricot's JavaScript API requires an authenticated user; anonymous calls
fail. This directory is public, so the gadget cannot read Wild Apricot live.
Instead a scheduled job reads Wild Apricot with a server-side API key, writes
`docs/roster.js`, and the gadget loads that file.

The gadget loads it with a `<script>` tag rather than `fetch()`, so there is no
CORS configuration to get wrong and the file can be hosted anywhere.

## Files

| File | What it is |
|---|---|
| `mitin-directory-gadget.html` | Paste into a Custom HTML gadget on the directory page |
| `refresh_roster.py` | Reads Wild Apricot, writes `roster.js` |
| `.github/workflows/refresh-roster.yml` | Runs the script daily and publishes the result |
| `wa-api-test.html` | Temporary diagnostic. Delete the gadget after use |
| `build_roster.py` | Builds a roster from a spreadsheet export instead of the API |

## Setup

1. **Create a server application** in Wild Apricot: Settings → Authorized
   applications → Server application. Copy its **API key** (not the Client ID —
   this script uses the API key).

2. **Put it in a GitHub secret.** Repo → Settings → Secrets and variables →
   Actions → New repository secret, named `WA_API_KEY`.
   The API key is full-access. It must never appear in the gadget, which is
   readable by every visitor.

3. **Turn on GitHub Pages.** Repo → Settings → Pages → Deploy from a branch →
   `main` / `/docs`. The roster is then served at
   `https://<owner>.github.io/<repo>/roster.js`.

4. **Run the workflow once by hand** from the Actions tab to generate the
   first `docs/roster.js`.

5. **Set `ROSTER_URL`** at the top of the gadget to that URL, set `ACCOUNT_ID`
   so member names link to their Wild Apricot profiles, and paste the gadget in.

## Running it locally

    export WA_API_KEY='...'
    python3 refresh_roster.py -o docs/roster.js

No dependencies beyond the Python standard library.

## Changing a field name

Field names live in `refresh_roster.py`, not in the gadget. The gadget receives
data already shaped — pairs assembled, agency and individual service fields
merged into one list per member.

## Things that will bite you

**Privacy settings are per field, and both halves of a pair need the same one.**
If `Interpret FROM 1` is visible and `Interpret TO 1` is not, the slot is
incomplete and the pair is dropped. The script prints a NOTE for every
half-filled slot it finds — check the Actions log for these.

**Only members with "Access to profile by others" set to yes are included.**
That matches what a public directory is allowed to show.

**A member with no pairs on file still appears** in the roster but will never
match a language search. The script counts these on each run.

## If the membership outgrows this

The daily refresh means a new member appears within a day. If that becomes too
slow, the options in order of effort are: run the workflow manually after adding
someone (a button in the Actions tab), shorten the cron schedule, or move the
directory behind a member login, where the live API does work.
