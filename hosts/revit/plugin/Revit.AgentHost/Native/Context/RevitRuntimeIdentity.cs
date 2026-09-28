namespace Revit.AgentHost.Native.Context;

/// <summary>
/// 持有当前 Revit AgentHost 进程生命周期内唯一且稳定的 runtime identity。
/// 所有 READ surface 必须引用同一个值，禁止各自生成新的 Host identity。
/// </summary>
public static class RevitRuntimeIdentity
{
    /// <summary>
    /// 当前 AgentHost 进程的稳定 Host instance identity。
    /// </summary>
    public static string HostInstanceId { get; } = $"revit-{Guid.NewGuid():N}";
}
