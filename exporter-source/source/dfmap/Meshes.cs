using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Objects.Core.Math;
using Newtonsoft.Json.Linq;

namespace Dfmap;

/// <summary>Decoded LOD0 triangle geometry of one static mesh (UE units = cm, left-handed Z-up).</summary>
public sealed class MeshData
{
    public string Path { get; set; }
    /// <summary>Original Unreal asset when Path identifies a component material variant.</summary>
    public string SourceAssetPath { get; set; }
    public float[] Positions { get; set; }   // 3 per vertex
    public float[] Normals { get; set; }     // 3 per vertex
    public float[] Uvs { get; set; }         // 2 per vertex
    public float[][] UvChannels { get; set; } // Every authored channel, including blend-mask UVs.
    public byte[] Colors { get; set; }       // Authored RGBA8 vertex masks; never infer missing colours.
    public string ColorBufferState { get; set; } = "unavailable";
    public uint[] Indices { get; set; }
    public int[] SectionMaterial { get; set; }

    /// <summary>
    /// Material instance asset paths from UStaticMesh.StaticMaterials. CUE4Parse assigns its
    /// typed StaticMaterials field only after the point where Game parsing fails, but
    /// the tagged property itself is read fine, so it is pulled from Properties instead.
    /// </summary>
    public List<string> Materials { get; set; } = new();

    /// <summary>Per-triangle material slot index, when the section table was readable.</summary>
    public int[] FaceMaterial { get; set; }

    public float[] BoundsMin { get; set; }
    public float[] BoundsMax { get; set; }

    public int VertexCount => Positions?.Length / 3 ?? 0;
    public int TriangleCount => Indices?.Length / 3 ?? 0;
    public long ApproxBytes => (long)(Positions?.Length ?? 0) * 4 + (Normals?.Length ?? 0) * 4
                               + (Uvs?.Length ?? 0) * 4 + (Indices?.Length ?? 0) * 4;
}

/// <summary>Loads and decodes UStaticMesh assets, caching by object path.</summary>
public sealed class MeshCache
{
    private readonly IFileProvider _provider;
    private readonly string _meshGame;
    private Newtonsoft.Json.JsonSerializerSettings _json;
    private readonly Dictionary<string, MeshData> _cache = new(StringComparer.OrdinalIgnoreCase);
    public readonly List<string> Failures = new();
    public readonly Dictionary<string, int> SkipReasons = new();
    public readonly List<string> SkippedPaths = new();
    public readonly StreamedMesh.Stats StreamedStats = new();
    public int Decoded => _cache.Count;
    public int StreamedDecoded { get; private set; }

    /// <summary>Meshes whose CUE4Parse decode fell outside the asset's declared ExtendedBounds.</summary>
    public int BoundsRejected;

    /// <summary>Every successfully decoded mesh (used to enumerate the materials actually in use).</summary>
    public IEnumerable<MeshData> DecodedMeshes => _cache.Values.Where(v => v is not null);

    public MeshCache(IFileProvider provider, string meshGame = null)
    {
        _provider = provider;
        _meshGame = meshGame;
    }

    /// <summary>path looks like "DeltaForce/Content/A/B/C.SM_Name".</summary>
    public MeshData Get(string path)
    {
        if (path is null) return null;
        if (_cache.TryGetValue(path, out var hit)) return hit;

        MeshData data = null;
        try
        {
            var (pkgPath, objName) = SplitObjectPath(path);
            if (objName.Contains(':')) throw new InvalidDataException($"blueprint sub-object, not a mesh asset: {path}");
            UStaticMesh mesh;
            using (new GameSwapScope(_provider, _meshGame))
            {
                mesh = _provider.LoadPackageObject<UStaticMesh>(pkgPath, objName);
            }
            if (mesh is null) { lock (SkipReasons) Bump("LoadPackageObject returned null"); }
            else
            {
                var materials = ReadMaterialPaths(mesh);
                var bounds = ReadExtendedBounds(mesh);
                data = Decode(path, mesh, out var why);
                if (data is not null && bounds is not null && !WithinDecoded(data, bounds))
                {
                    // CUE4Parse's own reader can return a LOD that does not fit the bounds the
                    // asset declares, which places garbage geometry in the scene. Drop it and
                    // let the streamed decoder try; the count is reported either way.
                    BoundsRejected++;
                    if (SkippedPaths.Count < 500)
                        SkippedPaths.Add($"CUE4Parse decode outside ExtendedBounds :: {path} " +
                                         $"({Describe(data)} vs {Describe(bounds)})");
                    data = null;
                }
                if (data is null)
                {
                    // CUE4Parse bails out in FDeltaForceStaticMeshRenderData for this game build;
                    // read the streamed LOD blobs ourselves instead of giving up. The declared
                    // bounds are handed over so the decoder can pick the blob that fits them.
                    data = StreamedMesh.Decode(_provider, path, StreamedStats,
                                               bounds?[..3], bounds?[3..]);
                    if (data is not null) StreamedDecoded++;
                }
                if (data is not null && materials.Count > 0) data.Materials = materials;
                if (data is not null && data.FaceMaterial is null && data.Materials.Count>1)
                {
                    var table=MeshSections.Find(_provider,data);
                    if(table is not null)
                    {
                        data.FaceMaterial=MeshSections.FaceMaterials(data,table.Sections);
                        data.SectionMaterial=table.Sections.Select(s=>s.MaterialIndex).ToArray();
                    }
                }
                if (data is null)
                {
                    lock (SkipReasons)
                    {
                        Bump(why ?? "unknown");
                        if (SkippedPaths.Count < 500) SkippedPaths.Add($"{why} :: {path}");
                    }
                }
            }
        }
        catch (Exception ex)
        {
            lock (Failures) Failures.Add($"{path}: {ex.GetType().Name}: {ex.Message}");
        }
        _cache[path] = data;   // cache failures as null so we don't retry
        return data;
    }

    /// <summary>
    /// The mesh's declared local-space bounds, as {minX,minY,minZ,maxX,maxY,maxZ} in cm.
    ///
    /// Every UStaticMesh asset carries ExtendedBounds = Origin +/- BoxExtent, and the cooked
    /// decoder's output must fit inside it. That makes it an independent check on a decode:
    /// a wrong stride or a mis-located vertex block produces geometry well outside the box.
    /// </summary>
    private float[] ReadExtendedBounds(UStaticMesh mesh)
    {
        try
        {
            _json ??= Inspect.BuildJsonSettings(_provider);
            var settings = Newtonsoft.Json.JsonSerializer.Create(_json);
            var json = JObject.FromObject(mesh, settings);
            var b = json["Properties"]?["ExtendedBounds"] as JObject;
            if (b is null) return null;
            float V(string group, string axis) =>
                b[group]?[axis]?.Value<float>() ?? 0f;
            var o = new[] { V("Origin", "X"), V("Origin", "Y"), V("Origin", "Z") };
            var e = new[] { V("BoxExtent", "X"), V("BoxExtent", "Y"), V("BoxExtent", "Z") };
            if (e.All(v => v <= 0f)) return null;
            return new[]
            {
                o[0] - e[0], o[1] - e[1], o[2] - e[2],
                o[0] + e[0], o[1] + e[1], o[2] + e[2],
            };
        }
        catch { return null; }
    }

    /// <summary>True when a decode fits inside the declared bounds (with a small tolerance).</summary>
    private static bool WithinDecoded(MeshData d, float[] bounds)
    {
        if (d.BoundsMin is null || d.BoundsMax is null) return true;
        for (var a = 0; a < 3; a++)
        {
            var span = bounds[a + 3] - bounds[a];
            var slack = MathF.Max(1.0f, span * 0.02f);
            if (d.BoundsMin[a] < bounds[a] - slack) return false;
            if (d.BoundsMax[a] > bounds[a + 3] + slack) return false;
        }
        return true;
    }

    private static string Describe(MeshData d) =>
        $"({d.BoundsMin[0]:0.#},{d.BoundsMin[1]:0.#},{d.BoundsMin[2]:0.#}).." +
        $"({d.BoundsMax[0]:0.#},{d.BoundsMax[1]:0.#},{d.BoundsMax[2]:0.#})";

    private static string Describe(float[] b) =>
        $"({b[0]:0.#},{b[1]:0.#},{b[2]:0.#})..({b[3]:0.#},{b[4]:0.#},{b[5]:0.#})";

    private void Bump(string reason)
    {
        SkipReasons[reason] = SkipReasons.GetValueOrDefault(reason) + 1;
    }

    /// <summary>
    /// Material instance paths from the StaticMaterials tagged property. UStaticMesh's typed
    /// field is only assigned near the end of Deserialize - past the point where Game
    /// parsing throws - so read the property directly instead. When even the typed property
    /// comes back empty the same data is pulled out of the JSON view of the object, which
    /// walks the raw tag list and therefore survives the truncated typed deserialisation.
    /// </summary>
    private List<string> ReadMaterialPaths(UStaticMesh mesh)
    {
        var list = new List<string>();
        try
        {
            var mats = mesh.GetOrDefault<CUE4Parse.UE4.Assets.Exports.StaticMesh.FStaticMaterial[]>("StaticMaterials");
            if (mats is not null)
            {
                foreach (var m in mats)
                {
                    string path = null;
                    var idx = m?.MaterialInterface;
                    if (idx is not null && !idx.IsNull)
                        path = mesh.Owner?.ResolvePackageIndex(idx)?.GetPathName();
                    list.Add(path ?? m?.MaterialSlotName.Text ?? "");
                }
                if (list.Any(p => !string.IsNullOrEmpty(p))) return list;
                list.Clear();
            }
        }
        catch { /* fall through to the JSON view */ }

        try
        {
            _json ??= Inspect.BuildJsonSettings(_provider);
            var settings = Newtonsoft.Json.JsonSerializer.Create(_json);
            var json = Newtonsoft.Json.Linq.JObject.FromObject(mesh, settings);
            var slots = json["Properties"]?["StaticMaterials"] as Newtonsoft.Json.Linq.JArray;
            if (slots is null) return list;
            foreach (var slot in slots)
            {
                var name = slot["MaterialSlotName"]?.Value<string>();
                var reference = slot["MaterialInterface"] as Newtonsoft.Json.Linq.JObject;
                list.Add(TextureRef(reference) ?? name ?? "");
            }
        }
        catch { /* materials are best-effort */ }
        return list;
    }

    /// <summary>Serialized object reference -> "Package/Object.Object" loadable path.</summary>
    private static string TextureRef(Newtonsoft.Json.Linq.JObject reference)
    {
        var objectName = reference?["ObjectName"]?.Value<string>();
        var objectPath = reference?["ObjectPath"]?.Value<string>();
        if (objectName is null || objectPath is null) return null;
        var quote = objectName.IndexOf('\'');
        var name = quote >= 0 ? objectName[(quote + 1)..].TrimEnd('\'') : objectName;
        if (name.Length == 0 || name == "None") return null;
        var pkg = objectPath;
        var dot = pkg.LastIndexOf('.');
        if (dot > 0 && int.TryParse(pkg[(dot + 1)..], out _)) pkg = pkg[..dot];
        return $"{pkg}.{name}";
    }

    /// <summary>
    /// Split "DeltaForce/Content/A/B/SM_X" or ".../SM_X.uasset" or ".../Pkg.SM_X"
    /// into (packagePath, objectName). NOTE: do not run this through IFileProvider.FixPath -
    /// it is not idempotent and appends a package extension on a second call.
    /// </summary>
    public static (string Package, string Object) SplitObjectPath(string path)
    {
        var p = path.Replace('\\', '/');
        var slash = p.LastIndexOf('/');
        var file = p[(slash + 1)..];
        foreach (var ext in new[] { ".uasset", ".umap", ".uexp", ".ubulk", ".uptnl" })
        {
            if (!file.EndsWith(ext, StringComparison.OrdinalIgnoreCase)) continue;
            file = file[..^ext.Length];
            p = p[..(slash + 1)] + file;
            break;
        }
        var dot = file.LastIndexOf('.');
        return dot > 0
            ? (p[..(slash + 1 + dot)], file[(dot + 1)..])
            : (p, file);
    }

    public static MeshData Decode(string path, UStaticMesh mesh) => Decode(path, mesh, out _);

    public static MeshData Decode(string path, UStaticMesh mesh, out string reason)
    {
        reason = null;
        var rd = mesh.RenderData;
        if (rd is null) { reason = "no RenderData"; return null; }
        if (rd.LODs is null || rd.LODs.Length == 0)
        {
            reason = rd.NaniteResources is not null ? "nanite-only (no classic LODs)" : "no LODs";
            return null;
        }
        var lod = rd.LODs[0];
        if (lod is null) { reason = "LOD0 is null"; return null; }
        if (lod.SkipLod) { reason = "LOD0 flagged SkipLod"; return null; }

        var verts = lod.PositionVertexBuffer?.Verts;
        var idx = lod.IndexBuffer?.Buffer;
        if (verts is null || verts.Length == 0) { reason = "empty position buffer"; return null; }
        if (idx is null || idx.Length == 0) { reason = "empty index buffer"; return null; }

        var n = verts.Length;
        var pos = new float[n * 3];
        var min = new[] { float.MaxValue, float.MaxValue, float.MaxValue };
        var max = new[] { float.MinValue, float.MinValue, float.MinValue };
        for (var i = 0; i < n; i++)
        {
            var v = verts[i];
            pos[i * 3] = v.X; pos[i * 3 + 1] = v.Y; pos[i * 3 + 2] = v.Z;
            for (var a = 0; a < 3; a++)
            {
                var c = a switch { 0 => v.X, 1 => v.Y, _ => v.Z };
                if (c < min[a]) min[a] = c;
                if (c > max[a]) max[a] = c;
            }
        }

        var nrm = new float[n * 3];
        var uv = new float[n * 2];
        var uvItems = lod.VertexBuffer?.UV;
        var uvChannels = uvItems is {Length: > 0} && uvItems[0].UV is {Length: > 0}
            ? Enumerable.Range(0,uvItems[0].UV.Length).Select(_=>new float[n*2]).ToArray() : null;
        for (var i = 0; i < n; i++)
        {
            if (uvItems is not null && i < uvItems.Length)
            {
                var it = uvItems[i];
                if (it.Normal is { Length: > 0 })
                {
                    var normal = it.Normal.Length > 2 ? it.Normal[2] : it.Normal[0];
                    nrm[i * 3] = normal.X;
                    nrm[i * 3 + 1] = normal.Y;
                    nrm[i * 3 + 2] = normal.Z;
                }
                if (it.UV is { Length: > 0 })
                {
                    uv[i * 2] = it.UV[0].U;
                    uv[i * 2 + 1] = it.UV[0].V;
                    for(var channel=0;uvChannels is not null && channel<uvChannels.Length && channel<it.UV.Length;channel++)
                    {uvChannels[channel][i*2]=it.UV[channel].U;uvChannels[channel][i*2+1]=it.UV[channel].V;}
                }
            }
        }

        var sections = lod.Sections ?? Array.Empty<FStaticMeshSection>();
        var secMat = new int[sections.Length];
        for (var i = 0; i < sections.Length; i++) secMat[i] = sections[i].MaterialIndex;

        return new MeshData
        {
            Path = path,
            Positions = pos,
            Normals = nrm,
            Uvs = uv,
            UvChannels = uvChannels,
            Colors = lod.ColorVertexBuffer?.Data is {} vertexColors && vertexColors.Length==n
                ? vertexColors.SelectMany(c=>new[]{c.R,c.G,c.B,c.A}).ToArray() : null,
            ColorBufferState = lod.ColorVertexBuffer?.Data?.Length==n ? "authored" : "default_white",
            Indices = idx.Select(x => (uint)x).ToArray(),
            SectionMaterial = secMat,
            FaceMaterial = sections.Length>0 ? MeshSections.FaceMaterials(new MeshData {Indices=idx.Select(x=>(uint)x).ToArray()},sections) : null,
            BoundsMin = min,
            BoundsMax = max,
        };
    }
}
