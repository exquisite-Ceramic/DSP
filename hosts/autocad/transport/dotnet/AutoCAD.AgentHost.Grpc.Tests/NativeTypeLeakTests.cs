using System.Reflection;
using Xunit;

namespace AutoCAD.AgentHost.Grpc.Tests;

public class NativeTypeLeakTests
{
    [Fact]
    public void TransportAssembly_DoesNotReference_Autodesk()
    {
        var assembly = typeof(global::AutoCAD.AgentHost.Grpc.IContractDispatchTarget).Assembly;
        var refs = assembly.GetReferencedAssemblies();

        Assert.DoesNotContain(refs, a =>
            a.Name?.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase) == true);
    }

    [Fact]
    public void PublicApi_DoesNotExpose_AutodeskTypes()
    {
        var assembly = typeof(global::AutoCAD.AgentHost.Grpc.IContractDispatchTarget).Assembly;

        foreach (var type in assembly.GetExportedTypes())
        {
            AssertNoAutodeskType(type.BaseType, $"{type.FullName} base type");

            foreach (var contract in type.GetInterfaces())
            {
                AssertNoAutodeskType(contract, $"{type.FullName} interface");
            }

            foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
            {
                AssertNoAutodeskType(property.PropertyType, $"{type.FullName}.{property.Name}");
            }

            foreach (var field in type.GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
            {
                AssertNoAutodeskType(field.FieldType, $"{type.FullName}.{field.Name}");
            }

            foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
            {
                AssertNoAutodeskType(method.ReturnType, $"{type.FullName}.{method.Name} return");
                foreach (var parameter in method.GetParameters())
                {
                    AssertNoAutodeskType(parameter.ParameterType, $"{type.FullName}.{method.Name}({parameter.Name})");
                }
            }

            foreach (var constructor in type.GetConstructors(BindingFlags.Public | BindingFlags.Instance))
            {
                foreach (var parameter in constructor.GetParameters())
                {
                    AssertNoAutodeskType(parameter.ParameterType, $"{type.FullName}.ctor({parameter.Name})");
                }
            }

            foreach (var evt in type.GetEvents(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
            {
                AssertNoAutodeskType(evt.EventHandlerType, $"{type.FullName}.{evt.Name} event");
            }
        }
    }

    private static void AssertNoAutodeskType(Type? type, string where)
    {
        if (type is null)
        {
            return;
        }

        var unwrapped = Nullable.GetUnderlyingType(type) ?? type;

        if (unwrapped.IsArray)
        {
            AssertNoAutodeskType(unwrapped.GetElementType(), where);
        }

        if (unwrapped.IsByRef || unwrapped.IsPointer)
        {
            AssertNoAutodeskType(unwrapped.GetElementType(), where);
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
