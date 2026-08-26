using HostContracts;

namespace AutoCAD.AgentHost.Identity;

/// <summary>Resolves a contract <see cref="HostEntityRef"/> to an in-drawing entity.</summary>
public static class HandleResolver
{
    /// <summary>
    /// Returns true when the entity exists and is not erased; resolved handle
    /// is echoed back for the caller to correlate with Native APIs.
    /// </summary>
    public static bool TryResolve(HostEntityRef entityRef, out object entity)
    {
        // Native.AutoCADEntityApi.GetEntityByHandle(handle) returns null when missing/erased.
        entity = Native.AutoCADEntityApi.GetEntityByHandle(entityRef.Handle);
        return entity is not null;
    }
}
