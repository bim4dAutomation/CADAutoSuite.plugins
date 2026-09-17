namespace Bim4D.RevitLinkDetector.Models
{
    /// <summary>
    /// One external reference found in the host file's saved TransmissionData —
    /// a Revit link, a CAD import, a keynote/decal file, etc. Only
    /// <c>RevitLink</c> entries are what the BIM4D upload dialog actually cares
    /// about (the linked .rvt models a composite upload needs), but the other
    /// types are still reported so the caller can decide what to do with them
    /// rather than have this add-in silently drop information.
    /// </summary>
    public class DetectedLink
    {
        /// <summary>
        /// The reference type as Revit's own <c>ExternalFileReferenceType</c>
        /// enum names it (e.g. "RevitLink", "CADLink", "DWFMarkup",
        /// "KeynoteTable", "Decal"). Kept as a string (not the enum itself) so
        /// this DTO has no Revit API dependency and can be reused by anything
        /// that only needs the JSON shape.
        /// </summary>
        public string ReferenceType { get; set; }

        /// <summary>
        /// The file name only (e.g. "ARE751_S_XX_MDL_2020.rvt"), extracted from
        /// <see cref="FullPath"/> — this is what the upload dialog matches
        /// against the files a user picks, since that's all a picked File
        /// object exposes.
        /// </summary>
        public string FileName { get; set; }

        /// <summary>
        /// The full path as last saved in the host file. Almost always a path
        /// on whatever machine last saved the host in Revit, not a path valid
        /// here — kept for diagnostics only, never for actually locating the
        /// file.
        /// </summary>
        public string FullPath { get; set; }

        /// <summary>
        /// True when Revit's saved path record could not be resolved to any
        /// usable string at all (a corrupt or very old reference record).
        /// When true, FileName/FullPath may be null or empty.
        /// </summary>
        public bool PathUnresolved { get; set; }
    }
}
