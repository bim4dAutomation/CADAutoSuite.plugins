#!/usr/bin/env node
/**
 * appbundle-register.js
 *
 * Registers RevitLinkDetector as one or more APS Design Automation
 * AppBundles + Activities — one pair per supported Revit year (2024,
 * 2025, 2026, 2027), each bound to its own engine, per
 * scripts/revit-versions.json.
 *
 * =====================================================================
 * DO NOT RUN THIS WITH --confirm WITHOUT MEANING TO. It creates real
 * resources against your APS account (an AppBundle, an AppBundle
 * version + alias, an Activity, an Activity alias — per year) and
 * Design Automation billing is consumption-based (Flex tokens / cloud
 * credits) once WorkItems actually run against these — this script
 * itself only registers definitions and does not run a WorkItem, but it
 * is still a real, non-trivial write against your account.
 *
 * This script defaults to a DRY RUN: it prints exactly what it would do
 * and makes no network calls that create/modify anything, EXCEPT
 * --list-engines, which is always read-only regardless of --confirm.
 * =====================================================================
 *
 * Usage:
 *   node scripts/appbundle-register.js --list-engines        # read-only: shows which Revit
 *                                                             # engines APS currently has, so
 *                                                             # you can check 2026/2027 for real
 *   node scripts/appbundle-register.js                       # dry run, all years in revit-versions.json
 *   node scripts/appbundle-register.js --year 2024           # dry run, just one year
 *   node scripts/appbundle-register.js --confirm             # register all years for real
 *   node scripts/appbundle-register.js --year 2024 --confirm # register just one year for real
 *
 * Prerequisites:
 *   1. bundle/RevitLinkDetector<year>.bundle.zip must already exist for
 *      each year you're registering — run:
 *        scripts\pack-bundle.ps1 -RevitYear <year>
 *   2. Environment variables (put them in scripts/.env, copied from
 *      scripts/env.example — gitignored, never commit real values):
 *        APS_CLIENT_ID
 *        APS_CLIENT_SECRET
 *      Use a dedicated APS app's 2-legged (client credentials)
 *      credentials with the "code:all" scope, not personal credentials.
 *
 * Requires Node 18+ (uses global fetch/FormData).
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const VERSIONS_PATH = path.join(__dirname, 'revit-versions.json');
const ACTIVITY_TEMPLATE_PATH = path.join(__dirname, 'activity.json');

const APS_BASE = 'https://developer.api.autodesk.com';
const DA_REGION = 'us-east';

// Every AppBundle and Activity is maintained under all three of these
// aliases. AppBundle aliases all point at the same (newest) version --
// there's only one build per registration run. Activity aliases do NOT
// share a version: each alias gets its own Activity version whose
// definition references the matching AppBundle alias (dev->dev,
// test->test, prod->prod), so repointing the "dev" AppBundle alias to a
// new build never touches what "prod" actually runs.
const ALIASES = ['dev', 'test', 'prod'];

function bundleName(year) { return `RevitLinkDetector${year}`; }
function activityName(year) { return `LinkDetectorActivity${year}`; }

function loadVersions() {
  return JSON.parse(fs.readFileSync(VERSIONS_PATH, 'utf8'));
}

function loadDotEnvIfPresent() {
  const envPath = path.join(__dirname, '.env');
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const val = trimmed.slice(eq + 1).trim();
    if (!(key in process.env)) process.env[key] = val;
  }
}

function requireEnv(name) {
  const v = process.env[name];
  if (!v) {
    console.error(`Missing required environment variable: ${name}`);
    console.error('Set it in scripts/.env (copy scripts/env.example) or export it before running this script.');
    process.exit(1);
  }
  return v;
}

async function getAccessToken(clientId, clientSecret) {
  const res = await fetch(`${APS_BASE}/authentication/v2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: clientId,
      client_secret: clientSecret,
      scope: 'code:all',
    }),
  });
  if (!res.ok) {
    throw new Error(`Auth failed: ${res.status} ${res.statusText} — ${await res.text()}`);
  }
  const json = await res.json();
  return json.access_token;
}

async function apsRequest(token, method, urlPath, body) {
  const res = await fetch(`${APS_BASE}${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json;
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    json = { raw: text };
  }
  return { status: res.status, ok: res.ok, json };
}

/** Read-only: lists every engine APS currently has for this account/region
 * and filters to Revit ones, so 2026's mid-cycle change and 2027's
 * unverified status (see revit-versions.json) can be checked against
 * reality instead of assumed. Paginates via the API's paginationToken. */
async function listRevitEngines(token) {
  const all = [];
  let url = `/da/${DA_REGION}/v3/engines`;
  while (url) {
    const res = await apsRequest(token, 'GET', url);
    if (!res.ok) throw new Error(`GET engines failed: ${res.status} ${JSON.stringify(res.json)}`);
    all.push(...(res.json.data || []));
    url = res.json.paginationToken
      ? `/da/${DA_REGION}/v3/engines?page=${encodeURIComponent(res.json.paginationToken)}`
      : null;
  }
  return all.filter((id) => id.toLowerCase().includes('revit'));
}

/** Ensures the account has a Design Automation "nickname" set (required
 * once per APS app before AppBundles/Activities can be created). Safe to
 * call repeatedly; APS returns 409 if already set, treated as fine. */
async function ensureNickname(token, nickname) {
  const res = await apsRequest(token, 'PATCH', `/da/${DA_REGION}/v3/forgeapps/me`, { nickname });
  if (res.ok || res.status === 409) {
    console.log(`Nickname OK (${res.status}).`);
    return;
  }
  // APS defaults an app's nickname to its own Client ID until a custom one
  // is set. Since we now always register under the Client ID itself (see
  // the nickname comment in main()), PATCHing it to that same value is a
  // no-op APS reports as 400, not success/409 - e.g.:
  //   {"nickname":["'<clientId>' is already the nickname by default (Parameter 'nickname')"]}
  // That's exactly the nickname we wanted, so treat it as OK.
  const nicknameErrors = res.json && res.json.nickname;
  const alreadyDefault =
    res.status === 400 &&
    Array.isArray(nicknameErrors) &&
    nicknameErrors.some(
      (msg) => typeof msg === 'string' && msg.toLowerCase().includes('already the nickname by default'),
    );
  if (alreadyDefault) {
    console.log('Nickname OK (already defaults to the Client ID).');
    return;
  }
  throw new Error(`Failed to set nickname: ${res.status} ${JSON.stringify(res.json)}`);
}

async function ensureAppBundle(token, year, engine) {
  const name = bundleName(year);
  const definition = {
    id: name,
    engine,
    description: `RevitLinkDetector for Revit ${year} — reads a host file's saved link references (TransmissionData) headlessly.`,
  };
  let res = await apsRequest(token, 'POST', `/da/${DA_REGION}/v3/appbundles`, definition);
  if (res.status === 409) {
    console.log(`  AppBundle ${name} already exists — creating a new version instead.`);
    res = await apsRequest(token, 'POST', `/da/${DA_REGION}/v3/appbundles/${name}/versions`, {
      engine,
      description: definition.description,
    });
  }
  if (!res.ok) {
    throw new Error(`AppBundle ${name} create/version failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  return res.json; // includes uploadParameters (S3 signed POST) and .version
}

async function uploadBundleZip(name, versionResponse, zipPath) {
  const { uploadParameters } = versionResponse;
  if (!uploadParameters) {
    throw new Error(`AppBundle ${name} version response had no uploadParameters — cannot upload zip.`);
  }
  const { endpointURL, formData } = uploadParameters;
  const body = new FormData();
  for (const [key, value] of Object.entries(formData)) {
    body.append(key, value);
  }
  body.append('file', new Blob([fs.readFileSync(zipPath)]), `${name}.bundle.zip`);

  const res = await fetch(endpointURL, { method: 'POST', body });
  if (!res.ok && res.status !== 204 && res.status !== 201) {
    throw new Error(`Zip upload to S3 failed for ${name}: ${res.status} ${await res.text()}`);
  }
  console.log(`  Uploaded ${path.basename(zipPath)} (AppBundle version ${versionResponse.version}).`);
}

async function ensureAppBundleAlias(token, year, version, alias) {
  const name = bundleName(year);
  let res = await apsRequest(token, 'POST', `/da/${DA_REGION}/v3/appbundles/${name}/aliases`, {
    id: alias,
    version,
  });
  if (res.status === 409) {
    res = await apsRequest(token, 'PATCH', `/da/${DA_REGION}/v3/appbundles/${name}/aliases/${alias}`, {
      version,
    });
  }
  if (!res.ok) {
    throw new Error(`AppBundle alias "${alias}" for ${name} failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  console.log(`  AppBundle alias "${alias}" -> version ${version}.`);
}

async function ensureActivity(token, year, engine, nickname, appBundleAlias) {
  const name = activityName(year);
  // Every placeholder must be replaced GLOBALLY (replaceAll, not replace):
  // activity.json's own _comment field mentions all four placeholder names
  // by their literal text, appearing before the real usage sites later in
  // the file - a non-global replace() would consume that comment mention
  // first and leave the real {{APPBUNDLE_ID}}/{{APPBUNDLE_ALIAS}} in
  // "appbundles" untouched (confirmed: this was a real bug, caught via a
  // live APS 400 "Cannot parse id." error on the unsubstituted string).
  const raw = fs.readFileSync(ACTIVITY_TEMPLATE_PATH, 'utf8')
    .replaceAll('{{YEAR}}', String(year))
    .replaceAll('{{ENGINE}}', engine)
    .replaceAll('{{APPBUNDLE_ID}}', `${nickname}.${bundleName(year)}`)
    .replaceAll('{{APPBUNDLE_ALIAS}}', appBundleAlias);
  const definition = JSON.parse(raw);
  delete definition._comment;

  let res = await apsRequest(token, 'POST', `/da/${DA_REGION}/v3/activities`, definition);
  if (res.status === 409) {
    console.log(`  Activity ${name} already exists — creating a new version instead.`);
    const { id, ...rest } = definition;
    res = await apsRequest(token, 'POST', `/da/${DA_REGION}/v3/activities/${name}/versions`, rest);
  }
  if (!res.ok) {
    throw new Error(`Activity ${name} create/version failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  return res.json;
}

async function ensureActivityAlias(token, year, version, alias) {
  const name = activityName(year);
  let res = await apsRequest(token, 'POST', `/da/${DA_REGION}/v3/activities/${name}/aliases`, {
    id: alias,
    version,
  });
  if (res.status === 409) {
    res = await apsRequest(token, 'PATCH', `/da/${DA_REGION}/v3/activities/${name}/aliases/${alias}`, {
      version,
    });
  }
  if (!res.ok) {
    throw new Error(`Activity alias "${alias}" for ${name} failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  console.log(`  Activity alias "${alias}" -> version ${version}.`);
}

/** Read-only: confirms an AppBundle+Activity are actually deployed for one
 * year/alias by GETting the alias (not trusting what a prior --confirm run
 * printed) and, for the Activity, fetching that exact version's definition
 * to confirm it references the matching AppBundle alias with no leftover
 * template placeholders. Never writes anything. Returns true/false. */
async function verifyRegistration(token, nickname, entry, alias) {
  const year = entry.year;
  console.log(`\n--- Verifying Revit ${year} / alias "${alias}" ---`);
  let ok = true;

  const bundleName_ = bundleName(year);
  const bundleAliasRes = await apsRequest(
    token, 'GET', `/da/${DA_REGION}/v3/appbundles/${bundleName_}/aliases/${alias}`,
  );
  if (bundleAliasRes.status === 404) {
    console.log(`  [MISSING] AppBundle ${bundleName_} has no "${alias}" alias.`);
    ok = false;
  } else if (!bundleAliasRes.ok) {
    console.log(`  [ERROR] Checking AppBundle alias failed: ${bundleAliasRes.status} ${JSON.stringify(bundleAliasRes.json)}`);
    ok = false;
  } else {
    console.log(`  [OK] AppBundle ${bundleName_} alias "${alias}" -> version ${bundleAliasRes.json.version}`);
  }

  const activityName_ = activityName(year);
  const activityAliasRes = await apsRequest(
    token, 'GET', `/da/${DA_REGION}/v3/activities/${activityName_}/aliases/${alias}`,
  );
  if (activityAliasRes.status === 404) {
    console.log(`  [MISSING] Activity ${activityName_} has no "${alias}" alias.`);
    ok = false;
  } else if (!activityAliasRes.ok) {
    console.log(`  [ERROR] Checking Activity alias failed: ${activityAliasRes.status} ${JSON.stringify(activityAliasRes.json)}`);
    ok = false;
  } else {
    const version = activityAliasRes.json.version;
    console.log(`  [OK] Activity ${activityName_} alias "${alias}" -> version ${version}`);

    const versionRes = await apsRequest(
      token, 'GET', `/da/${DA_REGION}/v3/activities/${activityName_}/versions/${version}`,
    );
    if (!versionRes.ok) {
      console.log(`  [ERROR] Could not fetch Activity version ${version} definition: ${versionRes.status} ${JSON.stringify(versionRes.json)}`);
      ok = false;
    } else {
      const def = versionRes.json;
      const expectedAppBundleRef = `${nickname}.${bundleName_}+${alias}`;
      const appbundles = def.appbundles || [];
      const bodyText = JSON.stringify(def);
      if (bodyText.includes('{{')) {
        console.log(`  [BUG] Activity version ${version} still has an unsubstituted {{...}} placeholder: ${bodyText}`);
        ok = false;
      } else if (appbundles.includes(expectedAppBundleRef)) {
        console.log(`  [OK] Activity version ${version} correctly references AppBundle "${expectedAppBundleRef}"`);
      } else {
        console.log(`  [MISMATCH] Activity version ${version} references ${JSON.stringify(appbundles)}, expected ["${expectedAppBundleRef}"]`);
        ok = false;
      }
      if (def.engine === entry.engine) {
        console.log(`  [OK] Engine matches: ${def.engine}`);
      } else {
        console.log(`  [MISMATCH] Engine is "${def.engine}", expected "${entry.engine}" (see revit-versions.json).`);
        ok = false;
      }
    }
  }

  if (ok) {
    console.log(`  READY. Activity ID for the backend to call:`);
    console.log(`    ${nickname}.${activityName_}+${alias}`);
  } else {
    console.log(`  NOT fully deployed for alias "${alias}" - see issues above. This is read-only`);
    console.log(`  and made no changes; re-run the registration command with --confirm to fix it.`);
  }
  return ok;
}

async function registerYear(token, nickname, entry, confirm, aliases) {
  console.log(`\n--- Revit ${entry.year} (engine ${entry.engine}, framework ${entry.tfm}) ---`);
  if (entry.status && entry.status !== 'stable') {
    console.log(`  NOTE [${entry.status}]: ${entry.note}`);
  }

  const zipPath = path.join(REPO_ROOT, 'bundle', `${bundleName(entry.year)}.bundle.zip`);
  const aliasList = aliases.map((a) => `"${a}"`).join('/');

  if (!confirm) {
    console.log(`  DRY RUN: would ensure AppBundle ${bundleName(entry.year)} (engine ${entry.engine}), upload`);
    console.log(`  ${zipPath}, alias it ${aliasList}, then create one Activity`);
    console.log(`  ${activityName(entry.year)} version per alias (each referencing the matching AppBundle`);
    console.log(`  alias) and alias it the same way.`);
    return;
  }

  if (!fs.existsSync(zipPath)) {
    console.error(`  SKIPPED: ${zipPath} not found. Run: pwsh scripts\\pack-bundle.ps1 -RevitYear ${entry.year}`);
    return;
  }

  const bundleVersionResp = await ensureAppBundle(token, entry.year, entry.engine);
  await uploadBundleZip(bundleName(entry.year), bundleVersionResp, zipPath);
  for (const alias of aliases) {
    await ensureAppBundleAlias(token, entry.year, bundleVersionResp.version, alias);
  }

  console.log(`  Done. Activity IDs for the backend to call:`);
  for (const alias of aliases) {
    const activityVersionResp = await ensureActivity(token, entry.year, entry.engine, nickname, alias);
    await ensureActivityAlias(token, entry.year, activityVersionResp.version, alias);
    console.log(`    [${alias}] ${nickname}.${activityName(entry.year)}+${alias}`);
  }
}

async function main() {
  loadDotEnvIfPresent();
  const args = process.argv.slice(2);
  const confirm = args.includes('--confirm');
  const listEnginesFlag = args.includes('--list-engines');
  const verifyFlag = args.includes('--verify');
  const yearArgIdx = args.indexOf('--year');
  const onlyYear = yearArgIdx !== -1 ? parseInt(args[yearArgIdx + 1], 10) : null;
  const aliasArgIdx = args.indexOf('--alias');
  const onlyAlias = aliasArgIdx !== -1 ? args[aliasArgIdx + 1] : null;
  if (onlyAlias && !ALIASES.includes(onlyAlias)) {
    console.error(`--alias must be one of ${ALIASES.join('/')}, got "${onlyAlias}".`);
    process.exit(1);
  }
  const aliasesToRegister = onlyAlias ? [onlyAlias] : ALIASES;

  const clientId = requireEnv('APS_CLIENT_ID');
  const clientSecret = requireEnv('APS_CLIENT_SECRET');

  if (listEnginesFlag) {
    // Always read-only, regardless of --confirm.
    console.log('Fetching current Design Automation engine list (read-only)...\n');
    const token = await getAccessToken(clientId, clientSecret);
    const revitEngines = await listRevitEngines(token);
    if (revitEngines.length === 0) {
      console.log('No Revit engines returned — check APS_CLIENT_ID/SECRET and region.');
    } else {
      console.log('Revit engines currently available on Design Automation:');
      revitEngines.sort().forEach((e) => console.log(`  ${e}`));
    }
    console.log('\nCross-check this list against scripts/revit-versions.json — especially the');
    console.log('2026 row (mid-cycle .NET 10 upgrade on 2026-09-21) and the 2027 row (unverified');
    console.log('as of 2026-09-16). Do not register a year whose engine isn\'t listed here.');
    return;
  }

  if (verifyFlag) {
    // Always read-only, regardless of --confirm: GETs the alias + Activity
    // version APS actually has, rather than trusting a prior run's console
    // output. Doesn't require --confirm.
    const versions = loadVersions();
    const targets = onlyYear ? versions.filter((v) => v.year === onlyYear) : versions;
    if (onlyYear && targets.length === 0) {
      console.error(`No entry for --year ${onlyYear} in scripts/revit-versions.json.`);
      process.exit(1);
    }
    const aliasesToCheck = onlyAlias ? [onlyAlias] : ALIASES;
    const nickname = clientId;
    const token = await getAccessToken(clientId, clientSecret);
    let allOk = true;
    for (const entry of targets) {
      for (const alias of aliasesToCheck) {
        const ok = await verifyRegistration(token, nickname, entry, alias);
        allOk = allOk && ok;
      }
    }
    console.log(allOk ? '\nAll checked combinations are deployed correctly.' : '\nSome combinations are NOT deployed correctly - see [MISSING]/[MISMATCH]/[BUG] above.');
    process.exitCode = allOk ? 0 : 1;
    return;
  }

  const versions = loadVersions();
  const targets = onlyYear ? versions.filter((v) => v.year === onlyYear) : versions;
  if (onlyYear && targets.length === 0) {
    console.error(`No entry for --year ${onlyYear} in scripts/revit-versions.json.`);
    process.exit(1);
  }

  console.log('RevitLinkDetector — APS Design Automation registration');
  console.log('======================================================');
  console.log(`Mode:  ${confirm ? 'CONFIRM (will create/update real APS resources and may incur usage)' : 'DRY RUN (default, safe — no network writes)'}`);
  console.log(`Years: ${targets.map((t) => t.year).join(', ')}`);

  // The "nickname" is just Autodesk's mnemonic stand-in for the Client ID
  // (https://aps.autodesk.com/en/docs/design-automation/v3/tutorials/revit/step3-create-nickname) -
  // using the Client ID itself means the backend and this script are always
  // in agreement on what it is, with no separate value to keep in sync.
  const nickname = clientId;
  const token = await getAccessToken(clientId, clientSecret);
  if (confirm) {
    await ensureNickname(token, nickname);
  }

  for (const entry of targets) {
    await registerYear(token, nickname, entry, confirm, aliasesToRegister);
  }

  if (!confirm) {
    console.log('\nRe-run with --confirm to actually register these against your APS account.');
    console.log('Add --year <2024|2025|2026|2027> to do just one, --alias <dev|test|prod> to');
    console.log('target just one environment, --list-engines to check what APS currently offers,');
    console.log('or --verify (read-only) to confirm an existing registration is actually deployed.');
  }
}

main().catch((err) => {
  console.error('\nFAILED:', err.message);
  process.exit(1);
});
