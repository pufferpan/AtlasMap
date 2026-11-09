using System.Text;
using Dfmap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

var output = args.Length > 0 ? Path.GetFullPath(args[0]) : Path.Combine(Path.GetTempPath(), "dfmap-integrity-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(output);
var tests = new List<object>();
void Require(bool ok, string text) { if (!ok) throw new InvalidOperationException(text); }
void Test(string name, Action test) { test(); tests.Add(new { name, passed = true }); Console.WriteLine("PASS " + name); }
var mesh = new MeshData
{
    Path = "/Game/Test/Shared.Shared", SourceAssetPath = "/Game/Test/Shared.Shared",
    Positions = new float[] { 0, 0, 0, 100, 0, 0, 0, 100, 0 },
    Normals = new float[] { 0, 0, 1, 0, 0, 1, 0, 0, 1 },
    Uvs = new float[] { 0, 0, 1, 0, 0, 1 },
    UvChannels = new[] { new float[] { 0, 0, 1, 0, 0, 1 }, new float[] { .2f, .3f, .5f, .6f, .8f, .9f } },
    Colors = new byte[] { 255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0 },
    ColorBufferState = "authored", Indices = new uint[] { 0, 1, 2 },
    Materials = new List<string> { "/Game/Materials/Default.Default" }, FaceMaterial = new[] { 0 },
    BoundsMin = new float[] { 0, 0, 0 }, BoundsMax = new float[] { 100, 100, 0 },
};
var source = new SourceInstanceMetadata
{
    SourceLevel = "/Game/Maps/A/Same.umap", SourceActor = "ActorA", SourceComponent = "Mesh0",
    SourceComponentPath = "/Game/Maps/A/Same:PersistentLevel.ActorA.Mesh0", UnrealMeshPath = mesh.Path,
    OverrideMaterials = new() { "/Game/Materials/Override.Override" },
    Visibility = new SourceVisibility { HiddenInGame = true, Visible = true },
    Collision = new SourceCollision { ProfileName = "IgnoreBullets", Responses = JObject.Parse("{\"Pawn\":\"Block\",\"Camera\":\"Ignore\"}") },
}.ForInstance(null);
var variant = MaterialBinding.Apply(mesh, source.OverrideMaterials);
Test("component overrides do not mutate shared mesh or geometry", () =>
{
    Require(mesh.Materials[0].EndsWith("Default.Default"), "shared material changed");
    Require(variant.Materials[0].EndsWith("Override.Override"), "override missing");
    Require(ReferenceEquals(mesh.Positions, variant.Positions), "geometry needlessly copied");
    Require(ReferenceEquals(mesh.UvChannels, variant.UvChannels) && ReferenceEquals(mesh.Colors, variant.Colors), "attributes changed");
});
Test("null override preserves the original slot", () => Require(ReferenceEquals(MaterialBinding.Apply(mesh, new string[] { null }), mesh), "null slot cleared source material"));
Test("different source directories and instance indexes have stable distinct IDs", () =>
{
    Require(source.SourceId == source.ForInstance(null).SourceId, "unstable identity");
    var other = new SourceInstanceMetadata { SourceLevel = "/Game/Maps/B/Same.umap", SourceComponentPath = source.SourceComponentPath }.ForInstance(null);
    Require(source.SourceId != other.SourceId && source.SourceId != source.ForInstance(0).SourceId, "source ID collision");
});
Test("visibility and material overrides participate in deduplication signature", () =>
{
    var visible = new SourceInstanceMetadata { OverrideMaterials = source.OverrideMaterials, Visibility = new SourceVisibility { HiddenInGame = false } };
    Require(source.AppearanceSignature() != visible.AppearanceSignature(), "hidden/visible coincident placements merged");
});
var writer = new GlbWriter();
writer.AddInstance(writer.AddMesh(mesh), new float[] { 1000, 2000, 3000 }, new float[3], new float[] { 1, 1, 1 }, "plain", source: new SourceInstanceMetadata
{ SourceLevel = "/Game/Maps/B/Same.umap", SourceComponentPath = "plain", UnrealMeshPath = mesh.Path }.ForInstance(null));
writer.AddInstance(writer.AddMesh(variant), new float[] { 1000, 2000, 3000 }, new float[3], new float[] { 1, 1, 1 }, source.SourceId, source: source);
var glb = Path.Combine(output, "metadata_regression.glb"); writer.Write(glb, "integrity-regression");
var data = File.ReadAllBytes(glb); var size = BitConverter.ToInt32(data, 12);
var doc = JObject.Parse(Encoding.UTF8.GetString(data, 20, size));
Test("GLB retains metadata, hidden flags, collision and override paths", () =>
{
    var meta = doc["nodes"].Single(n => n["extras"]?["dfmap"]?["sourceId"]?.Value<string>() == source.SourceId)["extras"]["dfmap"];
    Require(meta["sourceId"].Value<string>() == source.SourceId, "ID missing");
    Require(!meta["visibility"]["renderable"].Value<bool>(), "hidden flag lost");
    Require(meta["collision"]["profileName"].Value<string>() == "IgnoreBullets", "collision lost");
    Require(meta["overrideMaterials"][0].Value<string>() == source.OverrideMaterials[0], "override path lost");
});
Test("GLB retains every UV and authored vertex color without reversing indices", () =>
{
    var attributes = doc["meshes"][0]["primitives"][0]["attributes"];
    Require(attributes["TEXCOORD_1"] != null && attributes["COLOR_0"] != null, "attributes dropped");
    var accessor = doc["accessors"][doc["meshes"][0]["primitives"][0]["indices"].Value<int>()];
    var view = doc["bufferViews"][accessor["bufferView"].Value<int>()];
    var binStart = 20 + size + 8;
    var offset = binStart + (view["byteOffset"]?.Value<int>() ?? 0) + (accessor["byteOffset"]?.Value<int>() ?? 0);
    Require(accessor["componentType"].Value<int>() == 5125, "unexpected index type");
    Require(BitConverter.ToUInt32(data, offset) == 0 && BitConverter.ToUInt32(data, offset + 4) == 1 && BitConverter.ToUInt32(data, offset + 8) == 2, "winding changed");
});
Test("material variant binds separate material without cross-wiring", () =>
{
    var a = doc["meshes"][0]["primitives"][0]["material"].Value<int>();
    var b = doc["meshes"][1]["primitives"][0]["material"].Value<int>();
    Require(a != b, "different component bindings share wrong material");
    Require(doc["materials"][b]["extras"]["unrealMaterialPath"].Value<string>() == source.OverrideMaterials[0], "wrong full material path");
});
Test("native matrix translations convert to glTF metres with Y/Z permutation", () =>
{
    var m = GlbWriter.ConvertNativeMatrix(new float[] { 1,0,0,0, 0,1,0,0, 0,0,1,0, 1000,2000,3000,1 });
    Require(Math.Abs(m[12]-10)<.0001 && Math.Abs(m[13]-30)<.0001 && Math.Abs(m[14]-20)<.0001, "axis or unit changed");
});
var report = new { passed = tests.Count, tests, glb };
File.WriteAllText(Path.Combine(output, "export_integrity_tests.json"), JsonConvert.SerializeObject(report, Formatting.Indented));
Console.WriteLine(JsonConvert.SerializeObject(new { passed = tests.Count, glb }, Formatting.Indented));
