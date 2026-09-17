using System.Reflection;
using System.Runtime.InteropServices;

// General information about this assembly, surfaced e.g. in the Design
// Automation activity logs and file properties on the built DLL.
[assembly: AssemblyTitle("RevitLinkDetector")]
[assembly: AssemblyDescription("Reads a Revit host file's saved link references via TransmissionData, headless, for BIM4D's Design Automation 'detect links before upload' flow.")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyCompany("BIM4D Automation")]
[assembly: AssemblyProduct("RevitLinkDetector")]
[assembly: AssemblyCopyright("Copyright (c) BIM4D Automation")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]

// Not visible to COM.
[assembly: ComVisible(false)]

// A fixed GUID for this assembly (distinct from the AddInId used in the
// .addin manifest — that one identifies the Revit add-in registration;
// this one is the standard assembly GUID). Do not reuse this GUID for a
// different assembly.
[assembly: Guid("6c2a1e0b-6a2b-4a4c-8b7b-9f2e3a2f5c11")]

// Bump AssemblyVersion for any change to result.json's shape (consumers
// like the BIM4D backend's detect-links endpoint may want to check this).
// Keep AssemblyFileVersion in step with it unless there's a reason not to.
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
