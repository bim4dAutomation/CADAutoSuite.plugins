using System;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using DesignAutomationFramework;

namespace Bim4D.RevitLinkDetector
{
    /// <summary>
    /// Entry point Revit loads on startup inside the Design Automation
    /// sandbox (per the .addin manifest's FullClassName). This is an
    /// IExternalDBApplication, not IExternalCommand — Design Automation add-ins
    /// run headless (no UI), so they hook the DesignAutomationBridge's ready
    /// event instead of a ribbon command.
    ///
    /// This add-in does exactly one thing: read the host file's saved link
    /// references via TransmissionData (see LinkDetectionHandler) and write
    /// them out as JSON. It never opens the document and never needs the
    /// linked files to be present — see the project README for why that
    /// matters for BIM4D's "detect links before upload" flow.
    /// </summary>
    public class App : IExternalDBApplication
    {
        public ExternalDBApplicationResult OnStartup(ControlledApplication application)
        {
            DesignAutomationBridge.DesignAutomationReadyEvent += HandleDesignAutomationReadyEvent;
            return ExternalDBApplicationResult.Succeeded;
        }

        public ExternalDBApplicationResult OnShutdown(ControlledApplication application)
        {
            return ExternalDBApplicationResult.Succeeded;
        }

        private void HandleDesignAutomationReadyEvent(object sender, DesignAutomationReadyEventArgs e)
        {
            // Tell Design Automation we're handling completion ourselves rather
            // than having it do the default post-processing (which assumes a
            // document was opened and needs saving — we never open one).
            e.Succeeded = true;

            try
            {
                LinkDetectionHandler.Run(e.DesignAutomationData);
            }
            catch (Exception ex)
            {
                // A crash here would otherwise just look like a silent
                // WorkItem failure with no useful reason in the report.json
                // Design Automation returns — LinkDetectionHandler already
                // writes its own result.json on the success path, so on an
                // unexpected exception we make one last attempt to write an
                // error result instead of leaving nothing behind at all.
                LinkDetectionHandler.TryWriteFailureResult(ex);
            }
        }
    }
}
