using System.Diagnostics.CodeAnalysis;
using HostContracts;

namespace AutoCAD.AgentHost.Identity;

/// <summary>Resolves a contract HostEntityRef to an in-drawing entity.</summary>
public static class HandleResolver
{
    public static bool TryResolve(
        HostEntityRef entityRef,
        [NotNullWhen(true)] out object? entity)
    {
        entity = Native.AutoCADEntityApi.GetEntityByHandle(entityRef.NativeId);
        return entity is not null;
    }
}
