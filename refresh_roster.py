#!/usr/bin/env python3
"""
Refresh the MiTiN directory roster from Wild Apricot.

Reads contacts and field definitions through the Wild Apricot admin API and
writes roster.js — a single file the directory gadget loads with a <script>
tag. A script tag is not subject to CORS, so the file can be served from
anywhere (GitHub Pages, the Wild Apricot file manager, any static host).

Needs one environment variable:

    WA_API_KEY   Settings > Authorized applications > your server application

The API key is a full-access credential. Keep it in a GitHub Actions secret or
your shell environment. Never put it in the gadget — anything in a Custom HTML
gadget is visible to every visitor.

Usage:
    WA_API_KEY=... python3 refresh_roster.py            # writes roster.js
    WA_API_KEY=... python3 refresh_roster.py -o out.js
    WA_API_KEY=... python3 refresh_roster.py --account 123456
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TOKEN_URL = "https://oauth.wildapricot.org/auth/token"
API_BASE = "https://api.wildapricot.org/v2.2"
SLOTS = 10

PAIR_SETS = {
    "interpret": ("Interpret FROM {n}", "Interpret TO {n}"),
    "translate": ("Translate FROM {n}", "Translate TO {n}"),
}

# Agency and individual members fill parallel fields; the directory shows one
# person per row, so each pair of fields is merged into a single list.
MERGED = {
    "translationServices": ["Agency Translation Services", "Translation Services - Individual"],
    "interpretingServices": ["Agency Interpreting Services", "Interpreting Services Individual"],
    "otherServices": ["Agency - Other Services", "Other Services - Individual"],
    "interpretingModes": ["Agency Interpreting Modes", "Interpreting Modes - Individual"],
    "interpretingMethods": ["Agency Interpreting Methods", "Interpreting Methods - Individual"],
    "workLanguages": ["Work Languages - Agency Work", "Work Languages - Individual Work"],
}

SINGLE = {
    "org": "Organization",
    "bio": "Bio",
    "website": "Company Website",
    "city": "City",
    "state": "State",
    "area": "Area",
    "nativeLanguage": "Native Language",
    "certifications": "Certifications",
    "level": "Membership level",
}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def get_token(api_key):
    basic = base64.b64encode(("APIKEY:" + api_key).encode()).decode()
    body = urllib.parse.urlencode({"scope": "auto", "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    account_id = None
    for p in data.get("Permissions", []):
        if p.get("AccountId"):
            account_id = p["AccountId"]
            break
    return data["access_token"], account_id


def api_get(token, path):
    req = urllib.request.Request(
        API_BASE + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


# --------------------------------------------------------------------------
# Field values
# --------------------------------------------------------------------------

def label_of(value):
    """A field value is a string, an object with Label/Value, or a list of those."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(x for x in (label_of(v) for v in value) if x)
    if isinstance(value, dict):
        return label_of(value.get("Label", value.get("Value")))
    return str(value).strip()


def list_of(value):
    if isinstance(value, list):
        return [x for x in (label_of(v) for v in value) if x]
    text = label_of(value)
    return [p.strip() for p in text.split(",") if p.strip()] if text else []


def uniq(items):
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --------------------------------------------------------------------------
# Transform
# --------------------------------------------------------------------------

def build_catalog(fields):
    """Every allowed value per dropdown, so searchers see the full range."""
    allowed = {}
    for f in fields or []:
        name = f.get("FieldName")
        if name:
            allowed[name] = [label_of(v) for v in (f.get("AllowedValues") or [])]

    def union(names):
        out = []
        for n in names:
            out.extend(allowed.get(n, []))
        return sorted(uniq(out), key=str.casefold)

    # All twenty slots share one language list; union them so a slot configured
    # differently from the others doesn't drop a language.
    lang_fields = []
    for tmpl_from, tmpl_to in PAIR_SETS.values():
        for n in range(1, SLOTS + 1):
            lang_fields.append(tmpl_from.format(n=n))
            lang_fields.append(tmpl_to.format(n=n))

    return {
        "languages": union(lang_fields),
        "translationServices": union(MERGED["translationServices"]),
        "interpretingServices": union(MERGED["interpretingServices"]),
        "interpretingModes": union(MERGED["interpretingModes"]),
        "interpretingMethods": union(MERGED["interpretingMethods"]),
    }


def transform(contact, warnings):
    by = {}
    for f in contact.get("FieldValues", []):
        by[f.get("FieldName")] = f.get("Value")

    person = {
        "id": str(contact.get("Id", "")),
        "first": contact.get("FirstName") or "",
        "last": contact.get("LastName") or "",
    }
    person["name"] = (contact.get("DisplayName")
                      or " ".join(x for x in (person["first"], person["last"]) if x).strip())

    for key, field in SINGLE.items():
        person[key] = label_of(by.get(field))

    for key, sources in MERGED.items():
        values = []
        for src in sources:
            values.extend(list_of(by.get(src)))
        person[key] = uniq(values)

    # Positional pairing: slot n's FROM belongs with slot n's TO. A slot with
    # only one half present is reported rather than guessed at — the usual
    # cause is the two halves having different privacy settings.
    for key, (tmpl_from, tmpl_to) in PAIR_SETS.items():
        pairs = []
        for n in range(1, SLOTS + 1):
            src = label_of(by.get(tmpl_from.format(n=n)))
            tgt = label_of(by.get(tmpl_to.format(n=n)))
            if src and tgt:
                pairs.append([src, tgt])
            elif src or tgt:
                warnings.append(
                    "%s: %s slot %d has only one half filled (%s)"
                    % (person["name"] or person["id"], key, n,
                       tmpl_from.format(n=n) if src else tmpl_to.format(n=n))
                )
        person[key + "Pairs"] = pairs

    return person


def is_public(contact):
    """Only contacts whose profile is visible to others belong in a public directory."""
    for f in contact.get("FieldValues", []):
        if f.get("FieldName") == "Access to profile by others":
            return label_of(f.get("Value")).lower() in ("yes", "true")
    return False


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="roster.js")
    ap.add_argument("--account", help="Account ID (discovered from the token when omitted)")
    ap.add_argument("--include-private", action="store_true",
                    help="Include contacts whose profile is not visible to others.")
    args = ap.parse_args()

    api_key = os.environ.get("WA_API_KEY", "").strip()
    if not api_key:
        sys.exit("WA_API_KEY is not set. Create a server application under "
                 "Settings > Authorized applications and export its API key.")

    try:
        token, discovered = get_token(api_key)
    except urllib.error.HTTPError as e:
        sys.exit("Could not get a token (HTTP %s). Check the API key.\n%s"
                 % (e.code, e.read().decode(errors="replace")[:400]))

    account = args.account or discovered
    if not account:
        sys.exit("Could not determine the account ID. Pass --account.")
    print("Account %s" % account)

    try:
        fields = api_get(token, "/accounts/%s/contactfields" % account)
    except urllib.error.HTTPError as e:
        print("WARNING: could not read field definitions (HTTP %s). Dropdowns will "
              "fall back to values found in the data." % e.code, file=sys.stderr)
        fields = []

    data = api_get(token, "/accounts/%s/contacts?%s"
                   % (account, urllib.parse.urlencode({"$async": "false"})))
    contacts = data.get("Contacts", data if isinstance(data, list) else [])
    print("Fetched %d contacts" % len(contacts))

    warnings, members = [], []
    skipped_private = skipped_archived = no_pairs = 0

    for c in contacts:
        if c.get("IsArchived"):
            skipped_archived += 1
            continue
        if not args.include_private and not is_public(c):
            skipped_private += 1
            continue
        person = transform(c, warnings)
        if not person["interpretPairs"] and not person["translatePairs"]:
            no_pairs += 1
        members.append(person)

    members.sort(key=lambda m: (m["name"] or m["org"] or "").casefold())

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "catalog": build_catalog(fields),
        "members": members,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("/* MiTiN directory roster — generated %s. Do not edit by hand. */\n"
                % payload["generated"])
        f.write("window.MITIN_DIRECTORY = ")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    print("Wrote %d members to %s" % (len(members), args.out))
    print("  languages in catalog: %d" % len(payload["catalog"]["languages"]))
    if skipped_archived:
        print("  %d skipped (archived)" % skipped_archived)
    if skipped_private:
        print("  %d skipped (profile not visible to others)" % skipped_private)
    if no_pairs:
        print("  %d included with no language pairs on file" % no_pairs)
    for w in warnings:
        print("  NOTE: %s" % w, file=sys.stderr)


if __name__ == "__main__":
    main()
