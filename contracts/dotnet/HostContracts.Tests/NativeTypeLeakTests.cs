using System.Reflection;
using HostContracts;
using Xunit;

namespace HostContracts.Tests;

/// <summary>
/// CI gate for AR-001 / spec §23.1: the contract assembly MUST NOT expose or
/// reference any Autodesk.AutoCAD.* type. Native types appearing in the
/// serialized contract are a major-level breaking change.
/// </summary>
public class NativeTypeLeakTests
{
    [Fact]
    public void Assembly_DoesNotReference_AnyAutodeskAssembly()
    {
        var autodeskRefs = typeof(RequestEnvelope).Assembly.GetReferencedAssemblies()
            .Where(a => a.Name!.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase))
            .ToList();

        Assert.False(autodeskRefs.Count > 0,
            $"HostContracts references Autodesk assemblies: {string.Join(", ", autodeskRefs.Select(a => a.Name))}");
    }

    [Fact]
    public void NoPublicContractMember_Exposes_AnAutodeskType()
    {
        var assembly = typeof(RequestEnvelope).Assembly;

        foreach (var type in assembly.GetExportedTypes())
        {
            foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            {
                AssertNoAutodeskType(property.PropertyType, $"{type.Name}.{property.Name}");
            }

            foreach (var field in type.GetFields(BindingFlags.Public | BindingFlags.Instance))
            {
                AssertNoAutodeskType(field.FieldType, $"{type.Name}.{field.Name}");
            }
        }
    }

    private static void AssertNoAutodeskType(Type type, string where)
    {
        var unwrapped = Nullable.GetUnderlyingType(type) ?? type;

        if (unwrapped.IsArray)
        {
            AssertNoAutodeskType(unwrapped.GetElementType()!, where);
        }

        if (unwrapped.IsGenericType)
        {
            foreach (var argument in unwrapped.GetGenericArguments())
            {
                AssertNoAutodeskType(argument, where);
            }
        }

        var isAutodesk = unwrapped.Namespace?.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase) == true;
        Assert.False(isAutodesk, $"{where} exposes Autodesk type {unwrapped.FullName}");
    }
}
