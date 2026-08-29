using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.EditorInput;

namespace AutoCAD.AgentHost.Native;

/// <summary>
/// AutoCAD-only Host Canvas interaction wrappers. This Native zone is the only
/// place where Step26 interaction code may reference Autodesk APIs.
/// </summary>
public static class AutoCADInteractionApi
{
    public readonly record struct PointPromptResult(
        bool Cancelled,
        double X,
        double Y,
        double Z);

    public static PointPromptResult PickPoint(string? prompt)
    {
        var document = Application.DocumentManager.MdiActiveDocument
            ?? throw new InvalidOperationException("no active document.");
        var editor = document.Editor;
        var message = string.IsNullOrWhiteSpace(prompt)
            ? "\nPick a point: "
            : $"\n{prompt.Trim()} ";
        var options = new PromptPointOptions(message);
        var result = editor.GetPoint(options);

        if (result.Status != PromptStatus.OK)
        {
            return new PointPromptResult(true, 0.0, 0.0, 0.0);
        }

        var value = result.Value;
        return new PointPromptResult(false, value.X, value.Y, value.Z);
    }
}
