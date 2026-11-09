using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports.Component.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;

namespace Dfmap;

public static class DeltaForceTypes
{
    private static int _registered;
    public static void Register()
    {
        if (Interlocked.Exchange(ref _registered, 1) != 0) return;
        // These cooked game classes inherit the regular mesh/component layouts.
        // Without an explicit registration CUE4Parse creates generic UObjects,
        // so scene traversal silently loses their transforms and template meshes.
        ObjectTypeRegistry.RegisterClass("DFMDesStaticMeshComponent", typeof(UStaticMeshComponent));
        ObjectTypeRegistry.RegisterClass("DestructibleStaticMesh", typeof(UStaticMesh));
        ObjectTypeRegistry.RegisterClass("MeshDecalComponent", typeof(UStaticMeshComponent));
    }
}
