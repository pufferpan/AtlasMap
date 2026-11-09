using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Assets.Readers;

namespace Dfmap;

/// <summary>
/// A UStaticMesh subclass that is registered under the package's "StaticMesh" class name so
/// we can see exactly where CUE4Parse's own reader gives up.
///
/// CUE4Parse catches per-export deserialization errors and hands back a partially built
/// object (which is why UStaticMesh.RenderData comes back null with only a generic
/// "Could not read StaticMesh named X correctly" log line). Overriding Deserialize lets the
/// real exception - and the archive offset where it happened - reach us.
/// </summary>
public class TracingStaticMesh : UStaticMesh
{
    public static bool Verbose = true;
    public static readonly List<string> Failures = new();

    public override void Deserialize(FAssetArchive Ar, long validPos)
    {
        var start = Ar.Position;
        try
        {
            base.Deserialize(Ar, validPos);
        }
        catch (Exception ex)
        {
            var where = $"start={start} pos={Ar.Position} validPos={validPos}";
            if (Failures.Count < 200)
                lock (Failures) Failures.Add($"{Name}: {where}: {ex.GetType().Name}: {ex.Message}");
            if (Verbose)
            {
                Console.Error.WriteLine($"[atlas] UStaticMesh '{Name}' FAILED at {where}");
                Console.Error.WriteLine($"[atlas]   {ex.GetType().Name}: {ex.Message}");
                if (Environment.GetEnvironmentVariable("ATLASMAP_TRACE") == "1")
                    Console.Error.WriteLine(ex.StackTrace);
            }
            throw;
        }
    }

    public static void Register()
    {
        var t = typeof(TracingStaticMesh);
        ObjectTypeRegistry.RegisterClass("StaticMesh", t);
        ObjectTypeRegistry.RegisterClass(t);
    }
}
