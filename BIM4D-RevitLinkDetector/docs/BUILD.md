# Building RevitLinkDetector (Revit 2024–2027)

## ⚠ Time-sensitive: Revit 2026 engine changes .NET runtime on 2026-09-21

Autodesk's APS blog announced the Design Automation Revit 2026 engine is
being force-upgraded to **Revit 2026.5 + .NET 10 on 2026-09-21**, and
states they will **not** keep it on the older .NET version after that
migration. Concretely:

- Before 2026-09-21: build Revit 2026 with `-RevitYear 2026`, which uses
  `net8.0-windows` (see `scripts/revit-versions.json`).
- From 2026-09-21 onward: edit that row's `"tfm"` to `net10.0-windows`,
  rebuild, and re-register (`pack-bundle.ps1 -RevitYear 2026` then
  `appbundle-register.js --year 2026 --confirm`).

Run `node scripts/appbundle-register.js --list-engines` any time to check
what's actually live before you assume `revit-versions.json` is still
accurate — it's a plain read-only lookup, safe to run whenever.

## This must be built on Windows, in Visual Studio (or its Developer PowerShell) — not from this repo's cloud dev session

The cloud sandbox that authored these files has no `dotnet`/`msbuild`, no
Windows runtime, and no Revit install — it can create and edit the source
files, but it cannot compile or run them. You'll need Visual Studio (or
just the .NET SDK) on your actual Windows machine.

## Why this project targets three different .NET runtimes

Revit add-ins must be compiled for the exact .NET runtime the host Revit
uses, and that changed partway through 2024–2027:

| Revit year | Add-in runtime | Design Automation engine | Notes |
|---|---|---|---|
| 2024 | `net48` (.NET Framework 4.8) | `Autodesk.Revit+2024` | stable |
| 2025 | `net8.0-windows` (.NET 8) | `Autodesk.Revit+2025` | Autodesk previewed a possible .NET 10 move here too — not confirmed live yet |
| 2026 (initial) | `net8.0-windows` (.NET 8) | `Autodesk.Revit+2026` | **changes to net10.0-windows on 2026-09-21** — see warning above |
| 2027 | `net10.0-windows` (.NET 10) | `Autodesk.Revit+2027` | desktop confirmed .NET 10; **Design Automation engine availability unverified as of 2026-09-16** — check `--list-engines` first |

`scripts/revit-versions.json` is the single source of truth for this
table (target framework, engine id, `RuntimeRequirements` series, and any
open caveat) — both `pack-bundle.ps1` and `appbundle-register.js` read it,
so updating that file is how you keep the whole toolchain in sync as
Autodesk ships or retires engines. `RevitLinkDetector.csproj` multi-targets
all three frameworks (`<TargetFrameworks>net48;net8.0-windows;net10.0-windows</TargetFrameworks>`)
from one shared set of `.cs` files — the Revit API surface this add-in
uses (`TransmissionData`, `ExternalFileReference`, `ModelPathUtils`) is
narrow and stable across all four years, so no `#if` conditional
compilation was needed. Because `IExternalDBApplication` — this add-in's
entry point — lives entirely in `RevitAPI.dll` (`Autodesk.Revit.DB`), the
project never references `RevitAPIUI.dll` at all, which sidesteps the
usual WinForms/WPF SDK complications on the `net8.0-windows`/
`net10.0-windows` targets.

An AppBundle is bound to exactly **one** engine, so each Revit year gets
its own AppBundle (`RevitLinkDetector2024`, `...2025`, `...2026`,
`...2027`) and its own Activity (`LinkDetectorActivity2024`, etc.), each
in its own `bundle/RevitLinkDetector<year>.bundle/` folder — not one
bundle shared across years.

## Prerequisites

- Visual Studio 2022 (any edition) with the ".NET desktop development"
  workload, **or** just the .NET SDK (`dotnet --version` should show
  8.0+ — the SDK needs to be new enough to target `net10.0-windows` for
  the 2026.5+/2027 builds, even though it can still target `net48` too).
- Internet access to nuget.org. **You do NOT need any Revit year
  installed locally to build anymore** (added 2026-09-16) — by default
  `RevitLinkDetector.csproj` references two NuGet packages instead, one
  per supported year, and `dotnet restore`/`build` fetches them
  automatically:
  - [`Nice3point.Revit.Api.RevitAPI`](https://github.com/Nice3point/RevitApi) —
    community-maintained reference assemblies for `RevitAPI.dll`.
  - [`Autodesk.Forge.DesignAutomation.Revit`](https://www.nuget.org/packages/Autodesk.Forge.DesignAutomation.Revit) —
    published by Autodesk itself, provides `DesignAutomationFramework.dll`.

  Both are marked `ExcludeAssets="runtime"` in the `.csproj` — compile
  against them, never copy them into build output — and `pack-bundle.ps1`
  only ever copies `RevitLinkDetector.dll`/`Newtonsoft.Json.dll`/the
  `.addin` file into the AppBundle zip regardless, so the real DLLs the
  cloud engine already has are always what actually runs; these packages
  never ship anywhere.

  If you'd rather build against an actual local Revit install instead
  (exact DLL match for one engine, or nuget.org isn't reachable on your
  network), pass `-p:UseLocalRevitInstall=true -p:RevitApiDir="..."` to
  any `dotnet build` below — see the big comment at the top of
  `RevitLinkDetector.csproj` for the per-framework defaults it falls
  back to (`net48`→Revit 2024, `net8.0-windows`→Revit 2025,
  `net10.0-windows`→Revit 2027).

## Build one year

Either open `RevitLinkDetector.sln` in Visual Studio, pick the
Release configuration, and use **Build → Batch Build** to select just the
target framework you need (Visual Studio shows each `TargetFrameworks`
entry as a separate build target), or from Developer PowerShell:

```powershell
cd BIM4D-RevitLinkDetector

# Revit 2024
dotnet build src\RevitLinkDetector\RevitLinkDetector.csproj -c Release -f net48 -p:Platform=x64

# Revit 2025 (and Revit 2026 before 2026-09-21)
dotnet build src\RevitLinkDetector\RevitLinkDetector.csproj -c Release -f net8.0-windows -p:Platform=x64

# Revit 2027 (and Revit 2026 from 2026-09-21 onward)
dotnet build src\RevitLinkDetector\RevitLinkDetector.csproj -c Release -f net10.0-windows -p:Platform=x64
```

This only matters if you opted into `-p:UseLocalRevitInstall=true` above
(the default NuGet-package build doesn't read `RevitApiDir` at all). If a
Revit year isn't at the default install path in that mode, override it:

```powershell
dotnet build src\RevitLinkDetector\RevitLinkDetector.csproj -c Release -f net8.0-windows -p:Platform=x64 `
  -p:UseLocalRevitInstall=true -p:RevitApiDir="D:\Some\Other\Path\Revit 2026"
```

(Running `dotnet build` with no `-f` builds all three frameworks in one
pass — useful for a quick "does everything still compile" check, but
`pack-bundle.ps1` below is what you actually want for packaging.)

### Building one year from the Visual Studio IDE

If you'd rather not deal with `-f`/Developer PowerShell, `RevitLinkDetector.sln`
also has named Solution Configurations that each build exactly one year:
`Debug_2024`, `Debug_2025`, `Debug_2026`, `Release_2024`, `Release_2025`,
`Release_2026` (all `|x64`) — pick one from the standard Solution
Configurations dropdown in the toolbar and hit Build, no separate
"Target Framework" selector needed. (2025 and 2026 both build
`net8.0-windows`, same as the command line above; 2027 doesn't have a
named configuration yet — use `-f net10.0-windows` for it, or ask to
have `Debug_2027`/`Release_2027` added the same way.) These are on top
of the plain `Debug|x64`/`Release|x64` configurations, which still build
all three frameworks at once.

## Package into an AppBundle zip, per year

```powershell
.\scripts\pack-bundle.ps1 -RevitYear 2024
.\scripts\pack-bundle.ps1 -RevitYear 2025
.\scripts\pack-bundle.ps1 -RevitYear 2026   # rebuild after 2026-09-21 once revit-versions.json's tfm is updated
.\scripts\pack-bundle.ps1 -RevitYear 2027   # only once its engine is confirmed live — see --list-engines
```

Each run looks up that year's target framework/engine in
`scripts/revit-versions.json`, prints any open caveat for it, builds,
lays out `bundle\RevitLinkDetector<year>.bundle\Contents\`, and zips it to
`bundle\RevitLinkDetector<year>.bundle.zip` — the file the registration
script uploads for that year.

## Register with APS (creates real cloud resources — read this first)

```powershell
cd scripts
copy env.example .env
# edit .env with real APS_CLIENT_ID / APS_CLIENT_SECRET
cd ..

node scripts\appbundle-register.js --list-engines     # read-only: confirm which Revit engines actually exist right now

node scripts\appbundle-register.js                    # dry run, all years — prints the plan, changes nothing
node scripts\appbundle-register.js --year 2024         # dry run, just one year

node scripts\appbundle-register.js --confirm           # register every year in revit-versions.json for real
node scripts\appbundle-register.js --year 2024 --confirm  # register just Revit 2024 for real
node scripts\appbundle-register.js --year 2024 --alias dev --confirm  # just Revit 2024's dev alias

node scripts\appbundle-register.js --verify --year 2024 --alias dev  # read-only: confirm it's really deployed
```

`--verify` doesn't trust the console output from a prior `--confirm` run -
it makes fresh GET calls to APS to confirm the AppBundle alias and Activity
alias actually exist, that the Activity's stored definition really
references the matching AppBundle alias (not a leftover
`{{APPBUNDLE_ID}}`-style template placeholder — this is exactly the class
of bug a live registration surfaced once already), and that the engine
matches `revit-versions.json`. It never writes anything and ignores
`--confirm`. Drop `--year`/`--alias` to check every year/alias combination
at once.

`appbundle-register.js` defaults to a dry run on purpose; `--list-engines`
is always read-only regardless of `--confirm`. Passing `--confirm` creates
or updates, **per year you target**: one AppBundle version, aliased under
all three of `dev`, `test`, and `prod` (they all point at that same
build); and three separate Activity versions — one per alias — each
version's definition referencing the matching AppBundle alias
(`dev`'s Activity calls the AppBundle's `dev` alias, and so on), aliased
`dev`/`test`/`prod` to match. That keeps the three environments
independent: repointing the AppBundle's `dev` alias at a new build never
changes what the `prod`-aliased Activity actually runs. Registering them
is not itself expensive, but every WorkItem later run against any of
these Activities consumes Design Automation usage (Flex tokens / cloud
credits under APS's current pricing) — this is a real, billed cloud
action once WorkItems start running, not a no-op. Register one year at a
time with `--year` if you're not ready to commit all four yet — the 2027
row in particular should not be registered until `--list-engines` shows
its engine actually exists.

## Testing without wiring up the BIM4D backend yet

Before writing the backend's `detect-links` endpoint, you can sanity-check
any one year's Activity directly:

1. Upload a sample host `.rvt` for that Revit year to an APS OSS bucket
   (or use one already uploaded for the viewer).
2. `POST /da/us-east/v3/workitems` referencing
   `<nickname>.LinkDetectorActivity<year>+dev` (or `+test`/`+prod` —
   pick whichever environment you're spiking against), with `hostModel`
   set to a signed GET URL for that file and `result` set to a signed
   PUT URL for wherever you want `result.json` to land.
3. Poll the WorkItem until it reports `success` or a failure code, then
   fetch the `result` URL.

This "spike" step (recommended in the implementation plan doc before
building out the backend/frontend integration) is the fastest way to get
a real latency number per year and confirm `result.json`'s shape before
writing more code around it.
