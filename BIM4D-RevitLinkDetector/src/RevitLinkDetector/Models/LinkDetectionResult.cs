using System.Collections.Generic;

namespace Bim4D.RevitLinkDetector.Models
{
    /// <summary>
    /// The full JSON payload this add-in writes as its Design Automation
    /// output — read back by the BIM4D backend's detect-links endpoint.
    /// </summary>
    public class LinkDetectionResult
    {
        /// <summary>True once TransmissionData was read successfully. False on any
        /// failure — check <see cref="ErrorMessage"/> in that case.</summary>
        public bool Success { get; set; }

        /// <summary>Present only when Success is false.</summary>
        public string ErrorMessage { get; set; }

        /// <summary>The host file name, echoed back for the caller's convenience
        /// (it already knows this, but it's a cheap sanity check).</summary>
        public string HostFileName { get; set; }

        /// <summary>Every external reference found, regardless of type.</summary>
        public List<DetectedLink> References { get; set; } = new List<DetectedLink>();

        /// <summary>Convenience subset: just the RevitLink entries' file names,
        /// deduplicated — this is the list the upload dialog actually wants
        /// to pre-populate or validate against.</summary>
        public List<string> LinkedRevitFileNames { get; set; } = new List<string>();
    }
}
