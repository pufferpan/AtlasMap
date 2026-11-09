using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Dfmap;

/// <summary>Lossless source placement state; absent cooked flags remain null.</summary>
public sealed class SourceInstanceMetadata
{
    [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; } = 2;
    [JsonProperty("sourceId")] public string SourceId { get; set; }
    [JsonProperty("sourceLevel")] public string SourceLevel { get; set; }
    [JsonProperty("sourceActor")] public string SourceActor { get; set; }
    [JsonProperty("sourceComponent")] public string SourceComponent { get; set; }
    [JsonProperty("sourceComponentPath")] public string SourceComponentPath { get; set; }
    [JsonProperty("sourceInstanceIndex")] public int? SourceInstanceIndex { get; set; }
    [JsonProperty("unrealMeshPath")] public string UnrealMeshPath { get; set; }
    [JsonProperty("overrideMaterials")] public List<string> OverrideMaterials { get; set; } = new();
    [JsonProperty("visibility")] public SourceVisibility Visibility { get; set; } = new();
    [JsonProperty("collision")] public SourceCollision Collision { get; set; } = new();

    public SourceInstanceMetadata ForInstance(int? index)
    {
        var clone = (SourceInstanceMetadata)MemberwiseClone();
        clone.SourceInstanceIndex = index;
        clone.SourceId = "DFI_" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            $"{SourceLevel}|{SourceComponentPath}|{index?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "single"}".ToLowerInvariant())))[..24].ToLowerInvariant();
        return clone;
    }

    public JObject ToJson() => JObject.FromObject(this);

    /// <summary>Do not merge coincident placements with different render/collision state.</summary>
    public string AppearanceSignature() => JsonConvert.SerializeObject(new
    {
        OverrideMaterials, Visibility, Collision,
    }, Formatting.None);
}

public sealed class SourceVisibility
{
    [JsonProperty("hiddenInGame")] public bool? HiddenInGame { get; set; }
    [JsonProperty("visible")] public bool? Visible { get; set; }
    [JsonProperty("ownerHidden")] public bool? OwnerHidden { get; set; }
    [JsonProperty("editorOnly")] public bool? EditorOnly { get; set; }
    [JsonProperty("renderable")] public bool Renderable => HiddenInGame != true && Visible != false
        && OwnerHidden != true && EditorOnly != true;
}

public sealed class SourceCollision
{
    [JsonProperty("profileName")] public string ProfileName { get; set; }
    [JsonProperty("enabled")] public string Enabled { get; set; }
    [JsonProperty("responses")] public JToken Responses { get; set; }
}

public static class MaterialBinding
{
    /// <summary>Null/empty overrides fall back by slot; never mutate cached geometry/materials.</summary>
    public static MeshData Apply(MeshData mesh, IReadOnlyList<string> overrides)
    {
        if (mesh is null || overrides is null || overrides.Count == 0) return mesh;
        var materials = mesh.Materials.ToList();
        for (var i = 0; i < overrides.Count; i++)
        {
            if (string.IsNullOrWhiteSpace(overrides[i])) continue;
            while (materials.Count <= i) materials.Add(null);
            materials[i] = overrides[i];
        }
        if (materials.SequenceEqual(mesh.Materials, StringComparer.OrdinalIgnoreCase)) return mesh;
        var signature = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            JsonConvert.SerializeObject(materials).ToLowerInvariant())))[..20].ToLowerInvariant();
        return new MeshData
        {
            Path = mesh.Path + "#materials_" + signature,
            SourceAssetPath = mesh.SourceAssetPath ?? mesh.Path,
            Positions = mesh.Positions, Normals = mesh.Normals, Uvs = mesh.Uvs,
            UvChannels = mesh.UvChannels, Colors = mesh.Colors, ColorBufferState = mesh.ColorBufferState,
            Indices = mesh.Indices, SectionMaterial = mesh.SectionMaterial, FaceMaterial = mesh.FaceMaterial,
            BoundsMin = mesh.BoundsMin, BoundsMax = mesh.BoundsMax, Materials = materials,
        };
    }
}
