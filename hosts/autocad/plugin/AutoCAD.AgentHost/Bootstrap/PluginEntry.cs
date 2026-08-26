using Autodesk.AutoCAD.Runtime;

namespace AutoCAD.AgentHost.Bootstrap;

/// <summary>
/// AutoCAD entry point (NETLOAD target).
/// The only non-Native file that must touch the AutoCAD runtime surface:
/// everything else talks through <c>Native/*</c> wrappers (ADR-001).
/// </summary>
public class PluginEntry : IExtensionApplication
{
    private PluginLifecycle? _lifecycle;

    public void Initialize()
    {
        _lifecycle = new PluginLifecycle();
        _lifecycle.Start();
    }

    public void Terminate()
    {
        _lifecycle?.Stop();
        _lifecycle = null;
    }
}
