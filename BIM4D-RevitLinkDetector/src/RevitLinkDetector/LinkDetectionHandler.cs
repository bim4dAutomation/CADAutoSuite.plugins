using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Autodesk.Revit.DB;
using Bim4D.RevitLinkDetector.Models;
using DesignAutomationFramework;
using Newtonsoft.Json;

namespace Bim4D.RevitLinkDetector
{
    /// <summary>
    /// Core logic: read a host .rvt's saved external references via
    /// TransmissionData and write the result as JSON.
    ///
    /// Deliberately does NOT call Application.OpenDocumentFile anywhere in
    /// this path. TransmissionData.ReadTransmissionData reads reference
    /// records straight from the file's own saved data — it needs the Revit
    /// engine's API context to be initialized (hence still running this
    /// inside Design Automation for Revit at all), but it does not need the
    /// document opened, and critically does NOT need the linked files
    /// themselves to be present or resolvable. That's exactly BIM4D's
    /// situation: at upload time we only have the host file.
    /// </summary>
    public static class LinkDetectionHandler
    {
        /// <summary>
        /// Local file name Design Automation downloads the host .rvt to,
        /// as configured on the Activity's input parameter (see
        /// activity.json in /scripts). Must match exactly.
        /// </summary>
        private const string InputLocalName = "hostModel.rvt";

        /// <summary>
        /// Local file name this add-in writes its result to; the Activity's
        /// output parameter uploads whatever exists at this path when the
        /// WorkItem finishes. Must match activity.json.
        /// </summary>
        private const string OutputLocalName = "result.json";

        public static void Run(DesignAutomationData data)
        {
            if (data == null)
            {
                TryWriteFailureResult(new ArgumentNullException(nameof(data)));
                return;
            }

            // DesignAutomationData.FilePath resolves to wherever the WorkItem
            // engine downloaded the input named InputLocalName. We deliberately
            // read from this raw path rather than from data.RevitDoc — see the
            // class remarks and the README's "open verb" note: the Activity is
            // defined WITHOUT requesting Revit auto-open the input, precisely
            // so this stays a pure file read.
            string inputPath = data.FilePath;
            if (string.IsNullOrWhiteSpace(inputPath) || !File.Exists(inputPath))
            {
                TryWriteFailureResult(new FileNotFoundException(
                    $"Expected input file at '{inputPath}' (local name '{InputLocalName}') was not found."));
                return;
            }

            var result = new LinkDetectionResult
            {
                HostFileName = Path.GetFileName(inputPath),
            };

            try
            {
                ModelPath modelPath = ModelPathUtils.ConvertUserVisiblePathToModelPath(inputPath);
                TransmissionData transmissionData = TransmissionData.ReadTransmissionData(modelPath);

                if (transmissionData == null)
                {
                    // A file with no external references at all (no links, no
                    // CAD imports) legitimately has no TransmissionData block —
                    // this is success with zero references, not a failure.
                    result.Success = true;
                }
                else
                {
                    ICollection<ElementId> refIds = transmissionData.GetAllExternalFileReferenceIds();
                    foreach (ElementId refId in refIds)
                    {
                        ExternalFileReference extRef = transmissionData.GetLastSavedReferenceData(refId);
                        result.References.Add(ToDetectedLink(extRef));
                    }

                    result.Success = true;
                    result.LinkedRevitFileNames = result.References
                        .Where(r => r.ReferenceType == ExternalFileReferenceType.RevitLink.ToString()
                                    && !r.PathUnresolved
                                    && !string.IsNullOrEmpty(r.FileName))
                        .Select(r => r.FileName)
                        .Distinct(StringComparer.OrdinalIgnoreCase)
                        .ToList();
                }
            }
            catch (Exception ex)
            {
                result.Success = false;
                result.ErrorMessage = ex.Message;
            }

            WriteResult(result);
        }

        private static DetectedLink ToDetectedLink(ExternalFileReference extRef)
        {
            var link = new DetectedLink
            {
                ReferenceType = extRef.ExternalFileReferenceType.ToString(),
            };

            try
            {
                ModelPath savedPath = extRef.GetPath();
                string userVisiblePath = ModelPathUtils.ConvertModelPathToUserVisiblePath(savedPath);
                link.FullPath = userVisiblePath;
                link.FileName = string.IsNullOrEmpty(userVisiblePath)
                    ? null
                    : Path.GetFileName(userVisiblePath);
                link.PathUnresolved = string.IsNullOrEmpty(userVisiblePath);
            }
            catch
            {
                // A reference whose saved path can't be converted at all (very
                // old record, cloud-model path in a format this Revit build
                // doesn't recognize, etc.) — report it as present but
                // unresolved rather than letting one bad entry fail the whole
                // WorkItem.
                link.PathUnresolved = true;
            }

            return link;
        }

        private static void WriteResult(LinkDetectionResult result)
        {
            string json = JsonConvert.SerializeObject(result, Formatting.Indented);
            File.WriteAllText(OutputLocalName, json);
        }

        /// <summary>
        /// Last-resort path for an exception App.cs didn't expect at all
        /// (not one Run() already turned into a Success:false result). Best
        /// effort only — if even this throws, the WorkItem just fails with
        /// no result.json, which is still a correct (if less informative)
        /// outcome for the caller polling for it.
        /// </summary>
        public static void TryWriteFailureResult(Exception ex)
        {
            try
            {
                WriteResult(new LinkDetectionResult
                {
                    Success = false,
                    ErrorMessage = ex?.Message ?? "Unknown error.",
                });
            }
            catch
            {
                // Nothing more we can do.
            }
        }
    }
}
