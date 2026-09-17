# RevitLinkDetector

A small Design Automation for Revit add-in that reads a host `.rvt` file's
saved link references (via the Revit API's `TransmissionData`) and reports
them as JSON — without opening the document and without needing the linked
files to be present. Supports **Revit 2024 through 2027**.

## Why this exists

BIM4D's viewer upload flow lets a user upload a Revit host model plus
whichever linked models they manually pick. Nothing today validates that
picked set against the host file's *actual* Revit links, which is how an
unrelated file (`HouseSample.rvt`) previously got accepted as a "linked
model" with no relationship to the host at all (see the project's
`revit-linked-model-upload-analysis.md` doc, "Live bug report #4").

The fix is to ask Revit itself, server-side, what the host file's real
links are, and use that to pre-populate/validate the upload dialog. There
is no lightweight APS Model Derivative or metadata endpoint that exposes
this — the Model Derivative References API explicitly does not support RVT
files, confirmed via Autodesk's own documentation/blog. The Revit API's
`TransmissionData` class is the sanctioned way to read this without opening
the file, but running Revit API code server-side requires Design
Automation for Revit — hence this separate add-in project rather than a
change to the existing NestJS backend alone.

## Which Revit years, and why more than one build

BIM4D's host files span multiple Revit years in practice, so this add-in
is built once per supported year rather than once overall — each Revit
year needs its own compiled binary (different .NET runtime) and its own
Design Automation AppBundle + Activity (bound to that year's engine):

| Revit year | Add-in runtime | Design Automation engine |
|---|---|---|
| 2024 | .NET Framework 4.8 | `Autodesk.Revit+2024` |
| 2025 | .NET 8 | `Autodesk.Revit+2025` |
| 2026 | .NET 8 → **.NET 10 from 2026-09-21** | `Autodesk.Revit+2026` |
| 2027 | .NET 10 | `Autodesk.Revit+2027` (unverified as of 2026-09-16 — see `docs/BUILD.md`) |

See `docs/BUILD.md` for the full explanation, the exact dates, and the
`--list-engines` command that checks the live truth instead of trusting
this table blindly. `scripts/revit-versions.json` is the single file that
actually drives the build/registration scripts — this table is a summary
of it, not the source of truth.

## How it fits together

```
BIM4D-FE  (upload dialog)
     |
     v
BIM4D-BE  (new: POST /models/detect-links, aware of the host's Revit year)
     |  submits a Design Automation WorkItem against that year's Activity, polls it
     v
APS Design Automation for Revit  (Autodesk.Revit+<year>)
     |  runs this add-in against the uploaded host .rvt
     v
RevitLinkDetector.dll  (this project, built per year)
     |  TransmissionData.ReadTransmissionData(...) -> result.json
     v
BIM4D-BE reads result.json, returns LinkedRevitFileNames to the dialog
```

This repo is **only** the Revit-side add-in (the bottom of that diagram) —
the backend endpoint and frontend dialog changes are separate, not-yet-
started work tracked in the implementation plan doc, not part of this
project. Note the backend endpoint will need to know which Revit year a
given host file is (Revit stores this in the file itself) to pick the
right Activity — that logic doesn't exist yet either.

## Structure

```
src/RevitLinkDetector/
  App.cs                      IExternalDBApplication entry point (shared across all years)
  LinkDetectionHandler.cs     Core TransmissionData read + JSON write (shared)
  Models/DetectedLink.cs      One external reference (DTO, shared)
  Models/LinkDetectionResult.cs  Full result.json shape (shared)
  RevitLinkDetector.addin     Revit add-in manifest (shared, packaged into every year's bundle)
  Properties/AssemblyInfo.cs
  RevitLinkDetector.csproj    Multi-targets net48 / net8.0-windows / net10.0-windows
bundle/
  RevitLinkDetector2024.bundle/PackageContents.xml   AppBundle manifest, Revit 2024 (checked in)
  RevitLinkDetector2025.bundle/PackageContents.xml   ...Revit 2025
  RevitLinkDetector2026.bundle/PackageContents.xml   ...Revit 2026
  RevitLinkDetector2027.bundle/PackageContents.xml   ...Revit 2027
  RevitLinkDetector<year>.bundle/Contents/           Populated per year by pack-bundle.ps1 (gitignored)
scripts/
  revit-versions.json          Single source of truth: year -> tfm/engine/RuntimeRequirements + caveats
  activity.json                Design Automation Activity TEMPLATE, shared across years ({{YEAR}}/{{ENGINE}} substituted)
  pack-bundle.ps1               Builds + packages ONE year at a time (-RevitYear)
  appbundle-register.js         Registers one/all years with APS (--year, --list-engines, defaults to dry-run)
  appbundle-register.py         Python port of the above (same flags, same dry-run-by-default safety) -
                                 for anyone who'd rather run this from Python than Node
  env.example                   Copy to scripts/.env with real APS credentials (gitignored)
docs/
  BUILD.md                      Full build/package/register walkthrough, incl. the 2026-09-21 engine change
RevitLinkDetector.sln
```

## Quick start

See [`docs/BUILD.md`](docs/BUILD.md) for the full walkthrough, including a
time-sensitive note about the Revit 2026 Design Automation engine's
.NET runtime changing on 2026-09-21. Short version: this must be built in
Visual Studio on Windows (the cloud session that authored these files
cannot compile .NET/Revit projects) — but as of 2026-09-16 you no longer
need any Revit year installed locally to do that build; `RevitLinkDetector.csproj`
references `Nice3point.Revit.Api.RevitAPI` + `Autodesk.Forge.DesignAutomation.Revit`
from NuGet by default (see `docs/BUILD.md`'s Prerequisites section for the
opt-out if you'd rather build against a real local install). Build one
year at a time with `scripts\pack-bundle.ps1 -RevitYear <year>`, then
register per year with `node scripts\appbundle-register.js --year <year> --confirm`
— that last step creates real, billed cloud resources, so it's a
deliberate flag rather than the default behavior, and `--list-engines`
lets you check what APS actually has before you commit to a year.
