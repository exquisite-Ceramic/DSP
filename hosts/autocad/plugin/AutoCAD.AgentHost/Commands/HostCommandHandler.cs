using HostContracts;

namespace AutoCAD.AgentHost.Commands;

/// <summary>
/// Base class for host command handlers. Handlers are pure contract-to-contract:
/// all AutoCAD access goes through <c>Native/*</c> and <c>Execution/*</c> (ADR-001).
/// </summary>
public abstract class HostCommandHandler
{
    /// <summary>Command type this handler serves, e.g. <c>model.move</c>.</summary>
    public abstract string CommandType { get; }

    public abstract HostCommandResult Execute(HostCommand command);
}

/// <summary>Registry mapping command types to handler instances.</summary>
public sealed class HostCommandHandlerRegistry
{
    private readonly Dictionary<string, HostCommandHandler> _handlers = new(StringComparer.Ordinal);

    public HostCommandHandlerRegistry()
    {
        Register(new Context.CurrentDocumentHandler());
        Register(new Context.CurrentSelectionHandler());
        Register(new Design.ExtractNativeSnapshotHandler());
        Register(new View.FitEntitiesHandler());
        Register(new Interaction.PickPointHandler());
        Register(new Model.MoveHandler());
        Register(new Model.SetWallThicknessHandler());
        Register(new Model.OffsetHandler());
    }

    public void Register(HostCommandHandler handler) => _handlers[handler.CommandType] = handler;

    public HostCommandHandler Resolve(string commandType) =>
        _handlers.TryGetValue(commandType, out var handler)
            ? handler
            : throw new KeyNotFoundException($"unknown command type: {commandType}");
}