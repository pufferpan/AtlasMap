using Dfmap;
using Newtonsoft.Json;

// Batch-extract the stored height patches with one pak mount, preserving the
// original bytes. The local configuration and key file stay outside the source.
var config = JsonConvert.DeserializeObject<GameConfig>(File.ReadAllText(args[0]));
CUE4Parse.Compression.OodleHelper.Initialize(Path.GetFullPath("oodle-data-shared.dll"));
using var provider = Mount.Create(config, AesKeySet.Load(config.KeyFile));
var target = args[1];
Directory.CreateDirectory(target);
var prefix = "DeltaForce/Content/Maps/BuildMaps_HD/Iceland/Runtime/LandscapeCDLOD/Asset/CDLODAsset_Heightmap_";
var paths = provider.Files.Keys.Where(p => p.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
    && p.EndsWith(".uexp", StringComparison.OrdinalIgnoreCase)).Order().ToList();
foreach (var path in paths)
{
    var data = provider.Files[path].Read();
    File.WriteAllBytes(Path.Combine(target, Path.GetFileName(path)), data);
    Console.WriteLine($"{Path.GetFileName(path)} {data.Length}");
}
Console.WriteLine($"Extracted {paths.Count} original height assets.");
