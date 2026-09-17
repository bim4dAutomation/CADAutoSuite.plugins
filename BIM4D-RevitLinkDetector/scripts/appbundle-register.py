#!/usr/bin/env python3
"""
appbundle-register.py

Python port of appbundle-register.js: registers RevitLinkDetector as one or
more APS Design Automation AppBundles + Activities - one pair per supported
Revit year (2024, 2025, 2026, 2027), each bound to its own engine, per
scripts/revit-versions.json. Builds each year's Activity ID from that same
per-year data (LinkDetectorActivity<year>+prod), matching what
BIM4D-BE/apps/api/src/models/design-automation/revit-versions.ts expects.

This exists alongside appbundle-register.js (not instead of it) for anyone
who'd rather run this from Python than Node - the two are kept in lockstep
by hand; if you change one, change the other.

=========================================================================
DO NOT RUN THIS WITH --confirm WITHOUT MEANING TO. It creates real
resources against your APS account (an AppBundle, an AppBundle version +
alias, an Activity, an Activity alias - per year) and Design Automation
billing is consumption-based (Flex tokens / cloud credits) once WorkItems
actually run against these - this script itself only registers
definitions and does not run a WorkItem, but it is still a real,
non-trivial write against your account.

This script defaults to a DRY RUN: it prints exactly what it would do and
makes no network calls that create/modify anything, EXCEPT --list-engines,
which is always read-only regardless of --confirm.
=========================================================================

Usage:
    python scripts/appbundle-register.py --list-engines          # read-only: shows which Revit
                                                                  # engines APS currently has, so
                                                                  # you can check 2026/2027 for real
    python scripts/appbundle-register.py                         # dry run, all years in revit-versions.json
    python scripts/appbundle-register.py --year 2024             # dry run, just one year
    python scripts/appbundle-register.py --confirm               # register all years for real
    python scripts/appbundle-register.py --year 2024 --confirm   # register just one year for real

Prerequisites:
    1. bundle/RevitLinkDetector<year>.bundle.zip must already exist for
       each year you're registering - run:
         scripts\\pack-bundle.ps1 -RevitYear <year>
    2. Environment variables (put them in scripts/.env, copied from
       scripts/env.example - gitignored, never commit real values):
         APS_CLIENT_ID
         APS_CLIENT_SECRET
       Use a dedicated APS app's 2-legged (client credentials)
       credentials with the "code:all" scope, not personal credentials.

Standard library only - no pip install needed (mirrors the JS version's
"Node 18+, uses global fetch" - no npm install needed either).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
VERSIONS_PATH = SCRIPTS_DIR / "revit-versions.json"
ACTIVITY_TEMPLATE_PATH = SCRIPTS_DIR / "activity.json"
ENV_PATH = SCRIPTS_DIR / ".env"

APS_BASE = "https://developer.api.autodesk.com"
DA_REGION = "us-east"

# Every AppBundle and Activity is maintained under all three of these
# aliases. AppBundle aliases all point at the same (newest) version --
# there's only one build per registration run. Activity aliases do NOT
# share a version: each alias gets its own Activity version whose
# definition references the matching AppBundle alias (dev->dev,
# test->test, prod->prod), so repointing the "dev" AppBundle alias to a
# new build never touches what "prod" actually runs.
ALIASES = ["dev", "test", "prod"]


def bundle_name(year: int) -> str:
    return f"RevitLinkDetector{year}"


def activity_name(year: int) -> str:
    return f"LinkDetectorActivity{year}"


def load_versions() -> list[dict[str, Any]]:
    with open(VERSIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dotenv_if_present() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        print(
            "Set it in scripts/.env (copy scripts/env.example) or export it before running this script.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


class ApsHttpError(RuntimeError):
    pass


def _http_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    data: Optional[bytes] = None,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get_access_token(client_id: str, client_secret: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "code:all",
        }
    ).encode("utf-8")
    status, raw = _http_request(
        f"{APS_BASE}/authentication/v2/token",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    if status != 200:
        raise ApsHttpError(f"Auth failed: {status} - {raw.decode('utf-8', 'replace')}")
    return json.loads(raw)["access_token"]


def aps_request(
    token: str, method: str, url_path: str, body: Optional[dict[str, Any]] = None
) -> tuple[int, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    status, raw = _http_request(f"{APS_BASE}{url_path}", method=method, headers=headers, data=data)
    text = raw.decode("utf-8", "replace")
    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        parsed = {"raw": text}
    return status, parsed


def list_revit_engines(token: str) -> list[str]:
    """Read-only: lists every engine APS currently has for this account/
    region and filters to Revit ones, so 2026's mid-cycle change and 2027's
    unverified status (see revit-versions.json) can be checked against
    reality instead of assumed. Paginates via the API's paginationToken."""
    all_engines: list[str] = []
    url_path: Optional[str] = f"/da/{DA_REGION}/v3/engines"
    while url_path:
        status, parsed = aps_request(token, "GET", url_path)
        if status // 100 != 2:
            raise ApsHttpError(f"GET engines failed: {status} {parsed}")
        all_engines.extend(parsed.get("data", []))
        pagination_token = parsed.get("paginationToken")
        url_path = (
            f"/da/{DA_REGION}/v3/engines?page={urllib.parse.quote(pagination_token)}"
            if pagination_token
            else None
        )
    return [e for e in all_engines if "revit" in e.lower()]


def ensure_nickname(token: str, nickname: str) -> None:
    """Ensures the account has a Design Automation "nickname" set (required
    once per APS app before AppBundles/Activities can be created). Safe to
    call repeatedly; APS returns 409 if already set, treated as fine."""
    status, parsed = aps_request(token, "PATCH", f"/da/{DA_REGION}/v3/forgeapps/me", {"nickname": nickname})
    if status // 100 == 2 or status == 409:
        print(f"Nickname OK ({status}).")
        return
    # APS defaults an app's nickname to its own Client ID until a custom one
    # is set. Since we now always register under the Client ID itself (see
    # the nickname comment in main()), PATCHing it to that same value is a
    # no-op APS reports as 400, not success/409 - e.g.:
    #   {"nickname":["'<clientId>' is already the nickname by default (Parameter 'nickname')"]}
    # That's exactly the nickname we wanted, so treat it as OK.
    nickname_errors = parsed.get("nickname") if isinstance(parsed, dict) else None
    already_default = (
        status == 400
        and isinstance(nickname_errors, list)
        and any(
            isinstance(msg, str) and "already the nickname by default" in msg.lower()
            for msg in nickname_errors
        )
    )
    if already_default:
        print("Nickname OK (already defaults to the Client ID).")
        return
    raise ApsHttpError(f"Failed to set nickname: {status} {parsed}")


def ensure_appbundle(token: str, year: int, engine: str) -> dict[str, Any]:
    name = bundle_name(year)
    definition = {
        "id": name,
        "engine": engine,
        "description": (
            f"RevitLinkDetector for Revit {year} - reads a host file's saved link "
            "references (TransmissionData) headlessly."
        ),
    }
    status, parsed = aps_request(token, "POST", f"/da/{DA_REGION}/v3/appbundles", definition)
    if status == 409:
        print(f"  AppBundle {name} already exists - creating a new version instead.")
        status, parsed = aps_request(
            token,
            "POST",
            f"/da/{DA_REGION}/v3/appbundles/{name}/versions",
            {"engine": engine, "description": definition["description"]},
        )
    if status // 100 != 2:
        raise ApsHttpError(f"AppBundle {name} create/version failed: {status} {parsed}")
    return parsed  # includes uploadParameters (S3 signed POST) and .version


def _build_multipart_body(fields: dict[str, str], file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    """Builds a multipart/form-data body by hand (stdlib has no high-level
    helper for this) - equivalent to the JS version's `new FormData()` +
    per-key `.append()`, ending with the file part last, which is what
    S3's presigned-POST policy expects."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def upload_bundle_zip(name: str, version_response: dict[str, Any], zip_path: Path) -> None:
    upload_parameters = version_response.get("uploadParameters")
    if not upload_parameters:
        raise ApsHttpError(f"AppBundle {name} version response had no uploadParameters - cannot upload zip.")
    endpoint_url = upload_parameters["endpointURL"]
    form_data = upload_parameters["formData"]

    body, boundary = _build_multipart_body(
        form_data, "file", f"{name}.bundle.zip", zip_path.read_bytes()
    )
    status, raw = _http_request(
        endpoint_url,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        data=body,
    )
    if status not in (200, 201, 204):
        raise ApsHttpError(f"Zip upload to S3 failed for {name}: {status} {raw.decode('utf-8', 'replace')}")
    print(f"  Uploaded {zip_path.name} (AppBundle version {version_response['version']}).")


def ensure_appbundle_alias(token: str, year: int, version: int, alias: str) -> None:
    name = bundle_name(year)
    status, parsed = aps_request(
        token, "POST", f"/da/{DA_REGION}/v3/appbundles/{name}/aliases", {"id": alias, "version": version}
    )
    if status == 409:
        status, parsed = aps_request(
            token,
            "PATCH",
            f"/da/{DA_REGION}/v3/appbundles/{name}/aliases/{alias}",
            {"version": version},
        )
    if status // 100 != 2:
        raise ApsHttpError(f'AppBundle alias "{alias}" for {name} failed: {status} {parsed}')
    print(f'  AppBundle alias "{alias}" -> version {version}.')


def ensure_activity(token: str, year: int, engine: str, nickname: str, app_bundle_alias: str) -> dict[str, Any]:
    name = activity_name(year)
    raw_template = ACTIVITY_TEMPLATE_PATH.read_text(encoding="utf-8")
    # Every placeholder must be replaced with NO count limit (i.e. all
    # occurrences): activity.json's own _comment field mentions all four
    # placeholder names by their literal text, appearing before the real
    # usage sites later in the file - the previous count=1 here matched
    # THAT comment mention first and left the real
    # {{APPBUNDLE_ID}}/{{APPBUNDLE_ALIAS}} in "appbundles" unsubstituted
    # (confirmed: this was a real bug, caught via a live APS 400 "Cannot
    # parse id." error on the unsubstituted string).
    substituted = (
        raw_template.replace("{{YEAR}}", str(year))
        .replace("{{ENGINE}}", engine)
        .replace("{{APPBUNDLE_ID}}", f"{nickname}.{bundle_name(year)}")
        .replace("{{APPBUNDLE_ALIAS}}", app_bundle_alias)
    )
    definition = json.loads(substituted)
    definition.pop("_comment", None)

    status, parsed = aps_request(token, "POST", f"/da/{DA_REGION}/v3/activities", definition)
    if status == 409:
        print(f"  Activity {name} already exists - creating a new version instead.")
        version_body = {k: v for k, v in definition.items() if k != "id"}
        status, parsed = aps_request(token, "POST", f"/da/{DA_REGION}/v3/activities/{name}/versions", version_body)
    if status // 100 != 2:
        raise ApsHttpError(f"Activity {name} create/version failed: {status} {parsed}")
    return parsed


def ensure_activity_alias(token: str, year: int, version: int, alias: str) -> None:
    name = activity_name(year)
    status, parsed = aps_request(
        token, "POST", f"/da/{DA_REGION}/v3/activities/{name}/aliases", {"id": alias, "version": version}
    )
    if status == 409:
        status, parsed = aps_request(
            token,
            "PATCH",
            f"/da/{DA_REGION}/v3/activities/{name}/aliases/{alias}",
            {"version": version},
        )
    if status // 100 != 2:
        raise ApsHttpError(f'Activity alias "{alias}" for {name} failed: {status} {parsed}')
    print(f'  Activity alias "{alias}" -> version {version}.')


def verify_registration(token: str, nickname: str, entry: dict[str, Any], alias: str) -> bool:
    """Read-only: confirms an AppBundle+Activity are actually deployed for
    one year/alias by GETting the alias (not trusting what a prior --confirm
    run printed) and, for the Activity, fetching that exact version's
    definition to confirm it references the matching AppBundle alias with no
    leftover template placeholders. Never writes anything."""
    year = entry["year"]
    print(f'\n--- Verifying Revit {year} / alias "{alias}" ---')
    ok = True

    bundle_name_ = bundle_name(year)
    bundle_alias_status, bundle_alias_body = aps_request(
        token, "GET", f"/da/{DA_REGION}/v3/appbundles/{bundle_name_}/aliases/{alias}"
    )
    if bundle_alias_status == 404:
        print(f'  [MISSING] AppBundle {bundle_name_} has no "{alias}" alias.')
        ok = False
    elif bundle_alias_status // 100 != 2:
        print(f"  [ERROR] Checking AppBundle alias failed: {bundle_alias_status} {bundle_alias_body}")
        ok = False
    else:
        print(f'  [OK] AppBundle {bundle_name_} alias "{alias}" -> version {bundle_alias_body["version"]}')

    activity_name_ = activity_name(year)
    activity_alias_status, activity_alias_body = aps_request(
        token, "GET", f"/da/{DA_REGION}/v3/activities/{activity_name_}/aliases/{alias}"
    )
    if activity_alias_status == 404:
        print(f'  [MISSING] Activity {activity_name_} has no "{alias}" alias.')
        ok = False
    elif activity_alias_status // 100 != 2:
        print(f"  [ERROR] Checking Activity alias failed: {activity_alias_status} {activity_alias_body}")
        ok = False
    else:
        version = activity_alias_body["version"]
        print(f'  [OK] Activity {activity_name_} alias "{alias}" -> version {version}')

        version_status, version_body = aps_request(
            token, "GET", f"/da/{DA_REGION}/v3/activities/{activity_name_}/versions/{version}"
        )
        if version_status // 100 != 2:
            print(f"  [ERROR] Could not fetch Activity version {version} definition: {version_status} {version_body}")
            ok = False
        else:
            expected_appbundle_ref = f"{nickname}.{bundle_name_}+{alias}"
            appbundles = version_body.get("appbundles", [])
            body_text = json.dumps(version_body)
            if "{{" in body_text:
                print(f"  [BUG] Activity version {version} still has an unsubstituted {{{{...}}}} placeholder: {body_text}")
                ok = False
            elif expected_appbundle_ref in appbundles:
                print(f'  [OK] Activity version {version} correctly references AppBundle "{expected_appbundle_ref}"')
            else:
                print(f"  [MISMATCH] Activity version {version} references {appbundles}, expected ['{expected_appbundle_ref}']")
                ok = False
            if version_body.get("engine") == entry["engine"]:
                print(f"  [OK] Engine matches: {version_body.get('engine')}")
            else:
                print(f"  [MISMATCH] Engine is \"{version_body.get('engine')}\", expected \"{entry['engine']}\" (see revit-versions.json).")
                ok = False

    if ok:
        print("  READY. Activity ID for the backend to call:")
        print(f"    {nickname}.{activity_name_}+{alias}")
    else:
        print(f'  NOT fully deployed for alias "{alias}" - see issues above. This is read-only')
        print("  and made no changes; re-run the registration command with --confirm to fix it.")
    return ok


def register_year(
    token: str, nickname: str, entry: dict[str, Any], confirm: bool, aliases: list[str]
) -> None:
    year = entry["year"]
    print(f"\n--- Revit {year} (engine {entry['engine']}, framework {entry['tfm']}) ---")
    if entry.get("status") and entry["status"] != "stable":
        print(f"  NOTE [{entry['status']}]: {entry['note']}")

    zip_path = REPO_ROOT / "bundle" / f"{bundle_name(year)}.bundle.zip"
    alias_list = "/".join(f'"{a}"' for a in aliases)

    if not confirm:
        print(f"  DRY RUN: would ensure AppBundle {bundle_name(year)} (engine {entry['engine']}), upload")
        print(f"  {zip_path}, alias it {alias_list}, then create one Activity")
        print(f"  {activity_name(year)} version per alias (each referencing the matching AppBundle")
        print("  alias) and alias it the same way.")
        return

    if not zip_path.exists():
        print(
            f"  SKIPPED: {zip_path} not found. Run: pwsh scripts\\pack-bundle.ps1 -RevitYear {year}",
            file=sys.stderr,
        )
        return

    bundle_version_resp = ensure_appbundle(token, year, entry["engine"])
    upload_bundle_zip(bundle_name(year), bundle_version_resp, zip_path)
    for alias in aliases:
        ensure_appbundle_alias(token, year, bundle_version_resp["version"], alias)

    print("  Done. Activity IDs for the backend to call:")
    for alias in aliases:
        activity_version_resp = ensure_activity(token, year, entry["engine"], nickname, alias)
        ensure_activity_alias(token, year, activity_version_resp["version"], alias)
        print(f"    [{alias}] {nickname}.{activity_name(year)}+{alias}")


def main() -> None:
    load_dotenv_if_present()

    parser = argparse.ArgumentParser(
        description="Register RevitLinkDetector AppBundles + Activities with APS Design Automation, per Revit year."
    )
    parser.add_argument("--confirm", action="store_true", help="Actually create/update real APS resources.")
    parser.add_argument(
        "--list-engines",
        action="store_true",
        help="Read-only: list Revit engines APS currently has (always safe, ignores --confirm).",
    )
    parser.add_argument("--year", type=int, choices=[2024, 2025, 2026, 2027], help="Only register this one year.")
    parser.add_argument(
        "--alias",
        choices=ALIASES,
        help="Only register this one alias (dev/test/prod) instead of all three.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Read-only: confirm an existing registration is actually deployed (ignores --confirm).",
    )
    args = parser.parse_args()

    aliases_to_register = [args.alias] if args.alias else list(ALIASES)

    client_id = require_env("APS_CLIENT_ID")
    client_secret = require_env("APS_CLIENT_SECRET")

    if args.list_engines:
        print("Fetching current Design Automation engine list (read-only)...\n")
        token = get_access_token(client_id, client_secret)
        revit_engines = list_revit_engines(token)
        if not revit_engines:
            print("No Revit engines returned - check APS_CLIENT_ID/SECRET and region.")
        else:
            print("Revit engines currently available on Design Automation:")
            for engine in sorted(revit_engines):
                print(f"  {engine}")
        print("\nCross-check this list against scripts/revit-versions.json - especially the")
        print("2026 row (mid-cycle .NET 10 upgrade on 2026-09-21) and the 2027 row (unverified")
        print("as of 2026-09-16). Do not register a year whose engine isn't listed here.")
        return

    if args.verify:
        # Always read-only, regardless of --confirm: GETs the alias +
        # Activity version APS actually has, rather than trusting a prior
        # run's console output. Doesn't require --confirm.
        versions = load_versions()
        targets = [v for v in versions if v["year"] == args.year] if args.year else versions
        if args.year and not targets:
            print(f"No entry for --year {args.year} in scripts/revit-versions.json.", file=sys.stderr)
            sys.exit(1)
        aliases_to_check = [args.alias] if args.alias else list(ALIASES)
        nickname = client_id
        token = get_access_token(client_id, client_secret)
        all_ok = True
        for entry in targets:
            for alias in aliases_to_check:
                all_ok = verify_registration(token, nickname, entry, alias) and all_ok
        if all_ok:
            print("\nAll checked combinations are deployed correctly.")
        else:
            print("\nSome combinations are NOT deployed correctly - see [MISSING]/[MISMATCH]/[BUG] above.")
            sys.exit(1)
        return

    versions = load_versions()
    targets = [v for v in versions if v["year"] == args.year] if args.year else versions
    if args.year and not targets:
        print(f"No entry for --year {args.year} in scripts/revit-versions.json.", file=sys.stderr)
        sys.exit(1)

    print("RevitLinkDetector - APS Design Automation registration (Python)")
    print("=================================================================")
    mode = (
        "CONFIRM (will create/update real APS resources and may incur usage)"
        if args.confirm
        else "DRY RUN (default, safe - no network writes)"
    )
    print(f"Mode:  {mode}")
    print(f"Years: {', '.join(str(t['year']) for t in targets)}")

    # The "nickname" is just Autodesk's mnemonic stand-in for the Client ID
    # (https://aps.autodesk.com/en/docs/design-automation/v3/tutorials/revit/step3-create-nickname) -
    # using the Client ID itself means the backend and this script are always
    # in agreement on what it is, with no separate value to keep in sync.
    nickname = client_id
    token = get_access_token(client_id, client_secret)
    if args.confirm:
        ensure_nickname(token, nickname)

    for entry in targets:
        register_year(token, nickname, entry, args.confirm, aliases_to_register)

    if not args.confirm:
        print("\nRe-run with --confirm to actually register these against your APS account.")
        print("Add --year <2024|2025|2026|2027> to do just one, --alias <dev|test|prod> to")
        print("target just one environment, --list-engines to check what APS currently offers,")
        print("or --verify (read-only) to confirm an existing registration is actually deployed.")


if __name__ == "__main__":
    try:
        main()
    except ApsHttpError as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
