using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCAD.AgentHost.Execution;

/// <summary>
/// Runs a block of work inside an AutoCAD database transaction.
/// The transaction object stays inside Native boundaries; only the
/// committed/aborted outcome is observable to callers.
/// </summary>
public static class TransactionRunner
{
    public static void Run(Database database, Action<Transaction> work)
    {
        using var transaction = database.TransactionManager.StartTransaction();
        try
        {
            work(transaction);
            transaction.Commit();
        }
        catch
        {
            transaction.Abort();
            throw;
        }
    }
}
