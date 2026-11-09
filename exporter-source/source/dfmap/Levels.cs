using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Component;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.Engine;
using CUE4Parse.UE4.Objects.UObject;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using CUE4Parse.UE4.Assets.Objects;

namespace Dfmap;

/// <summary>One static-mesh instance placed in world space.</summary>
public sealed class MeshInstance
{
    public string Actor { get; set; }
    public string Component { get; set; }
    public string Mesh { get; set; }
    public string Type { get; set; }
    public float[] Loc { get; set; }
    public float[] Rot { get; set; }
    public float[] Scale { get; set; }
    /// <summary>Native affine transform, column-major, UE centimetres; avoids Euler round trips.</summary>
    public float[] MatrixUE { get; set; }

    /// <summary>
    /// World-space half-extent of the component, when the cooked package serialized it.
    /// This is the only footprint information available for meshes whose geometry is
    /// streamed into .ubulk and therefore cannot be decoded.
    /// </summary>
    public float[] Extent { get; set; }
    [JsonProperty("dfmap")] public SourceInstanceMetadata Source { get; set; }
}

/// <summary>A light component placed in the world (exported as KHR_lights_punctual).</summary>
public sealed class LightInstance
{
    public string Type { get; set; }        // Spot | Point | Rect | Directional | Sky | Fog
    public string Name { get; set; }
    public float[] Loc { get; set; }
    public float[] Rot { get; set; }        // roll / pitch / yaw
    public float Intensity { get; set; }
    public float[] Color { get; set; }      // linear RGB
    public float Radius { get; set; }
    public float InnerCone { get; set; }
    public float OuterCone { get; set; }
    public float SourceWidth { get; set; }
    public float SourceHeight { get; set; }
    public bool CastShadows { get; set; }
}

public sealed class LevelSummary
{
    public string Level { get; set; }
    public int ExportCount { get; set; }
    public int ActorCount { get; set; }
    public int InstanceCount { get; set; }
    public Dictionary<string, int> Classes { get; set; } = new();
    public Dictionary<string, int> Components { get; set; } = new();
    public float[] BoundsCenter { get; set; }
    public float[] BoundsExtent { get; set; }
    public List<MeshInstance> Instances { get; set; } = new();
    public List<LightInstance> Lights { get; set; } = new();
    public List<string> Errors { get; set; } = new();
}

/// <summary>
/// Extracts placed-geometry instances out of a cooked level package.
///
/// Why this works without any offset bookkeeping: in cooked UE levels every
/// placed actor's root component stores its ABSOLUTE world location, so merging
/// the tiled sub-levels of a DF map is (almost) plain concatenation.
/// </summary>
public static class Levels
{
    public static LevelSummary Extract(IFileProvider provider, string path,
                                       bool collectInstances = true, int maxInstances = int.MaxValue, bool includeHidden = false)
    {
        var summary = new LevelSummary { Level = path };
        var pkg = provider.LoadPackage(path);
        summary.ExportCount = pkg.ExportMapLength;

        ULevel level = null;
        var exports = new List<UObject>();
        foreach (var lazy in pkg.ExportsLazy)
        {
            UObject obj;
            try { obj = lazy.Value; }
            catch (Exception ex) { summary.Errors.Add($"export: {ex.Message}"); continue; }
            if (obj is null) continue;
            exports.Add(obj);
            if (obj is ULevel l && l.Name == "PersistentLevel") level = l;
        }
        level ??= exports.OfType<ULevel>().FirstOrDefault();
        var byObjectPath=exports.GroupBy(x=>x.GetPathName()).ToDictionary(g=>g.Key,g=>g.First());
        JsonSerializer serializer = null;

        if (level is not null)
        {
            foreach (var idx in level.Actors)
            {
                if (idx is null || idx.IsNull) continue;
                summary.ActorCount++;
                try
                {
                    var actor = idx.Load();
                    var cls = actor?.ExportType ?? "null";
                    summary.Classes[cls] = summary.Classes.GetValueOrDefault(cls) + 1;
                }
                catch (Exception ex) { summary.Errors.Add($"actor: {ex.Message}"); }
            }
        }

        // Components are exports whose Outer is the actor; walk every scene component
        // and record the ones that actually place geometry.
        foreach (var obj in exports)
        {
            // ---- lights ----
            var lightType = obj.ExportType switch
            {
                "SpotLightComponent" => "Spot",
                "PointLightComponent" => "Point",
                "RectLightComponent" => "Rect",
                "DirectionalLightComponent" => "Directional",
                "SkyLightComponent" => "Sky",
                "ExponentialHeightFogComponent" => "Fog",
                _ => null,
            };
            if (lightType is not null && obj is USceneComponent lc)
            {
                try
                {
                    var lt = lc.GetAbsoluteTransform();
                    var lr = lt.Rotation.Rotator();
                    var col = GetLinearColor(lc);
                    // Cooked packages strip properties that still hold their class default, so an
                    // absent radius/intensity means "default", not "zero".
                    float Def(string n, float d) => Has(lc, n) ? Prop(lc, n, d) : d;
                    summary.Lights.Add(new LightInstance
                    {
                        Type = lightType,
                        Name = obj.Name,
                        Loc = new[] { lt.Translation.X, lt.Translation.Y, lt.Translation.Z },
                        Rot = new[] { lr.Roll, lr.Pitch, lr.Yaw },
                        Intensity = Def("Intensity", lightType is "Directional" ? 10f : 5000f),
                        Color = col,
                        Radius = Def("AttenuationRadius", lightType is "Directional" or "Sky" ? 0f : 1000f),
                        InnerCone = Def("InnerConeAngle", 0f),
                        OuterCone = Def("OuterConeAngle", 44f),
                        SourceWidth = Def("SourceWidth", 0f),
                        SourceHeight = Def("SourceHeight", 0f),
                        CastShadows = Def("CastShadows", 1f) != 0f,
                    });
                }
                catch (Exception ex) { summary.Errors.Add($"light {obj.Name}: {ex.Message}"); }
                continue;
            }

            if (obj is not USceneComponent comp) continue;
            var type = comp.ExportType;
            summary.Components[type] = summary.Components.GetValueOrDefault(type) + 1;

            string meshPath = null;
            if (comp is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UStaticMeshComponent smc)
            {
                // Resolving the property index is NOT enough: for Blueprint actors the mesh
                // lives in a component template, and an unset StaticMesh resolves to the
                // component's native class import ("/Script/..."). Loading the object walks
                // the class-default chain and gives us the real mesh.
                try
                {
                    var mesh = smc.GetLoadedStaticMesh();
                    if (mesh is not null && !string.IsNullOrEmpty(mesh.Name)
                        && (string.Equals(mesh.ExportType, "StaticMesh", StringComparison.OrdinalIgnoreCase)
                            || string.Equals(mesh.ExportType, "DestructibleStaticMesh", StringComparison.OrdinalIgnoreCase)))
                    {
                        meshPath = mesh.GetPathName();
                    }
                }
                catch (Exception ex) { summary.Errors.Add($"mesh: {ex.Message}"); }
            }

            if (meshPath is null) continue;
            var ownerText=obj.Outer?.ToString()??"";
            var quote=ownerText.IndexOf('\'');
            var ownerPath=quote>=0?ownerText[(quote+1)..].TrimEnd('\''):ownerText;
            byObjectPath.TryGetValue(ownerPath,out var owner);
            bool? Flag(UObject item,string key) => item is not null && Has(item,key) ? item.GetOrDefault<bool>(key) : null;
            var source=new SourceInstanceMetadata
            {
                SourceLevel=path,SourceActor=ownerPath,SourceComponent=obj.Name,
                SourceComponentPath=obj.GetPathName(),UnrealMeshPath=meshPath,
                Visibility=new SourceVisibility
                {
                    HiddenInGame=Flag(comp,"bHiddenInGame"),Visible=Flag(comp,"bVisible"),
                    OwnerHidden=Flag(owner,"bHidden"),EditorOnly=Flag(owner,"bIsEditorOnlyActor"),
                },
            };
            try
            {
                var overrides=comp.GetOrDefault<FPackageIndex[]>("OverrideMaterials");
                if(overrides is not null)
                    foreach(var index in overrides)
                        source.OverrideMaterials.Add(index is null || index.IsNull ? null : comp.Owner?.ResolvePackageIndex(index)?.GetPathName());
            }
            catch(Exception ex){summary.Errors.Add($"override materials {obj.GetPathName()}: {ex.Message}");}
            if(Has(comp,"BodyInstance"))
                try
                {
                    var body=comp.GetOrDefault<FStructFallback>("BodyInstance");
                    if(body is not null)
                    {
                        serializer??=JsonSerializer.Create(Inspect.BuildJsonSettings(provider));
                        var json=JObject.FromObject(body,serializer);
                        source.Collision=new SourceCollision
                        {
                            ProfileName=json["CollisionProfileName"]?.Value<string>(),
                            Enabled=json["CollisionEnabled"]?.Value<string>(),
                            Responses=json["CollisionResponses"]?.DeepClone(),
                        };
                    }
                }
                catch(Exception ex){summary.Errors.Add($"collision metadata {obj.GetPathName()}: {ex.Message}");}
            if(!includeHidden && !source.Visibility.Renderable)continue;
            CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.FInstancedStaticMeshInstanceData[] perInstance = null;
            if (comp is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UInstancedStaticMeshComponent instanced)
            {
                try { perInstance = instanced.GetInstances(); }
                catch (Exception ex) { summary.Errors.Add($"instances {obj.Name}: {ex.Message}"); }
            }
            if (perInstance is { Length: > 0 })
            {
                var parent = comp.GetAbsoluteTransform();
                for(var instanceIndex=0;instanceIndex<perInstance.Length;instanceIndex++)
                {
                    var instance=perInstance[instanceIndex];
                    var tInstance = instance.TransformData * parent;
                    summary.InstanceCount++;
                    if (!collectInstances || summary.Instances.Count >= maxInstances) continue;
                    var rInstance = tInstance.Rotation.Rotator();
                    summary.Instances.Add(new MeshInstance
                    {
                        Actor = obj.Outer?.ToString(), Component = obj.Name, Mesh = meshPath, Type = type,
                        Loc = new[] {tInstance.Translation.X,tInstance.Translation.Y,tInstance.Translation.Z},
                        Rot = new[] {rInstance.Roll,rInstance.Pitch,rInstance.Yaw},
                        Scale = new[] {tInstance.Scale3D.X,tInstance.Scale3D.Y,tInstance.Scale3D.Z},
                        MatrixUE = NativeMatrix(tInstance),
                        Source = source.ForInstance(instanceIndex),
                    });
                }
                continue;
            }
            summary.InstanceCount++;
            if (!collectInstances || summary.Instances.Count >= maxInstances) continue;

            FTransform t;
            try { t = comp.GetAbsoluteTransform(); }
            catch { t = comp.GetComponentTransform(); }
            var rot = t.Rotation.Rotator();

            float[] extent = null;
            try
            {
                var b = comp.Bounds;
                var e = b.BoxExtent;
                if (e.X > 0 || e.Y > 0 || e.Z > 0) extent = new[] { e.X, e.Y, e.Z };
            }
            catch { /* bounds are not always serialized */ }

            summary.Instances.Add(new MeshInstance
            {
                Actor = obj.Outer?.ToString(),
                Component = obj.Name,
                Mesh = meshPath,
                Type = type,
                Loc = new[] { t.Translation.X, t.Translation.Y, t.Translation.Z },
                Rot = new[] { rot.Roll, rot.Pitch, rot.Yaw },
                Scale = new[] { t.Scale3D.X, t.Scale3D.Y, t.Scale3D.Z },
                MatrixUE = NativeMatrix(t),
                Extent = extent,
                Source = source.ForInstance(null),
            });
        }

        // LevelBounds gives the cell rectangle - the map's tiling unit.
        foreach (var obj in exports)
        {
            if (!obj.ExportType.Contains("LevelBounds")) continue;
            var box = obj.GetOrDefault<UObject>("RootComponent");
            if (box is not USceneComponent bc) continue;
            var t = bc.GetAbsoluteTransform();
            summary.BoundsCenter = new[] { t.Translation.X, t.Translation.Y, t.Translation.Z };
            try
            {
                var extent = bc.GetOrDefault<FVector>("BoxExtent");
                summary.BoundsExtent = new[] { extent.X * t.Scale3D.X, extent.Y * t.Scale3D.Y, extent.Z * t.Scale3D.Z };
            }
            catch { /* extent not serialized */ }
            break;
        }

        return summary;
    }

    public static float[] NativeMatrix(FTransform transform)
    {
        var x = transform.TransformVector(new FVector(1, 0, 0));
        var y = transform.TransformVector(new FVector(0, 1, 0));
        var z = transform.TransformVector(new FVector(0, 0, 1));
        var t = transform.Translation;
        return new[] { x.X,x.Y,x.Z,0f, y.X,y.Y,y.Z,0f, z.X,z.Y,z.Z,0f, t.X,t.Y,t.Z,1f };
    }

    public static int CmdLevel(IFileProvider provider, string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap level <umapPath> [outJson]"); return 2; }
        var path = args[0];
        var outFile = args.Length > 1 ? args[1] : null;

        var s = Extract(provider, path);
        Console.WriteLine($"level        : {s.Level}");
        Console.WriteLine($"exports      : {s.ExportCount}   actors: {s.ActorCount}   mesh instances: {s.Instances.Count}");
        Console.WriteLine($"level bounds : center={Fmt(s.BoundsCenter)} extent={Fmt(s.BoundsExtent)}");
        var byType = s.Lights.GroupBy(l => l.Type).OrderByDescending(g => g.Count()).ToList();
        Console.WriteLine($"lights       : {s.Lights.Count}" +
                          (byType.Count > 0 ? "  [" + string.Join(", ", byType.Select(g => $"{g.Key} {g.Count()}")) + "]" : ""));

        Console.WriteLine("actor classes:");
        foreach (var kv in s.Classes.OrderByDescending(k => k.Value).Take(15))
            Console.WriteLine($"  {kv.Value,6}  {kv.Key}");
        Console.WriteLine("scene components:");
        foreach (var kv in s.Components.OrderByDescending(k => k.Value).Take(15))
            Console.WriteLine($"  {kv.Value,6}  {kv.Key}");

        Console.WriteLine("first instances:");
        foreach (var i in s.Instances.Take(12))
            Console.WriteLine($"  {i.Actor}/{i.Component}  {Fmt(i.Loc)}  {Short(i.Mesh)}");

        if (s.Errors.Count > 0)
        {
            Console.WriteLine($"errors ({s.Errors.Count}), first 5:");
            foreach (var e in s.Errors.Take(5)) Console.WriteLine("  " + e);
        }

        if (outFile is not null)
        {
            File.WriteAllText(outFile, JsonConvert.SerializeObject(s, Formatting.Indented));
            Console.WriteLine($"wrote {outFile} ({new FileInfo(outFile).Length / 1024} KB)");
        }
        return 0;
    }

    private static string Fmt(float[] v) => v is null ? "-" : "(" + string.Join(", ", v.Select(x => x.ToString("0.##"))) + ")";

    /// <summary>True when the cooked package actually serialised this property.</summary>
    private static bool Has(UObject o, string name)
    {
        try
        {
            var props = o.Properties;
            if (props is null) return false;
            foreach (var p in props)
                if (p is not null && string.Equals(p.Name.Text, name, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }
        catch { return false; }
    }

    /// <summary>Read a tagged property without depending on CUE4Parse's typed fields.</summary>
    private static float Prop(UObject o, string name, float fallback)
    {
        try
        {
            var v = o.GetOrDefault<float>(name);
            return v;
        }
        catch { return fallback; }
    }

    /// <summary>Light colour: UE stores FColor (sRGB bytes); glTF wants linear floats.</summary>
    private static float[] GetLinearColor(USceneComponent comp)
    {
        try
        {
            var c = comp.GetOrDefault<CUE4Parse.UE4.Objects.Core.Math.FColor>("LightColor");
            static float Srgb(byte b)
            {
                var s = b / 255f;
                return s <= 0.04045f ? s / 12.92f : MathF.Pow((s + 0.055f) / 1.055f, 2.4f);
            }
            var rgb = new[] { Srgb(c.R), Srgb(c.G), Srgb(c.B) };
            if (rgb[0] <= 0f && rgb[1] <= 0f && rgb[2] <= 0f) return new[] { 1f, 1f, 1f };
            return rgb;
        }
        catch { return new[] { 1f, 1f, 1f }; }
    }

    private static string Short(string p)
    {
        if (p is null) return "-";
        var i = p.LastIndexOf('.');
        return i < 0 ? p : p[..(i + 1)] + p[(i + 1)..];
    }
}
