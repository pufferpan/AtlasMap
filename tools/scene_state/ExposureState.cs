using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;

// Retain only explicitly referenced exposure resources. No directory-wide
// discovery or inferred replacement asset is used for a missing reference.
internal static class ExposureState {
    static readonly HashSet<string> Roles = new(StringComparer.Ordinal) {
        "AutoExposureBiasCurve", "AutoExposureMeterMask",
        "LocalExposureHighlightContrastCurve", "LocalExposureShadowContrastCurve"
    };
    static string Package(string path) => EnvironmentState.CanonicalPath(path).Split('.')[0];
    static string? Reference(JsonElement value) {
        if(value.ValueKind!=JsonValueKind.Object)return null;
        if(value.TryGetProperty("AssetPathName",out var soft)&&soft.ValueKind==JsonValueKind.String) {
            var s=soft.GetString();return string.IsNullOrWhiteSpace(s)||s=="None"?null:EnvironmentState.CanonicalPath(s);
        }
        if(!value.TryGetProperty("ObjectPath",out var path)||path.ValueKind!=JsonValueKind.String)return null;
        var p=path.GetString();
        if(string.IsNullOrWhiteSpace(p)||p.StartsWith("/Script/"))return null;
        var label=value.TryGetProperty("ObjectName",out var name)?name.GetString()??"":"";
        var quoted=label.Split('\'').ElementAtOrDefault(1);
        var objectName=quoted?.Split(':').Last().Split('.').Last();
        return Package(p)+"."+(string.IsNullOrWhiteSpace(objectName)?Package(p).Split('/').Last():objectName);
    }
    static string Hash(string file) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(file)));

    internal static void Export(object cache,string output,Dictionary<string,string> packages,Func<string,string> dump) {
        var requested=new HashSet<(string path,string role)>();
        void Find(JsonElement value) {
            if(value.ValueKind==JsonValueKind.Object) {
                foreach(var field in value.EnumerateObject()) {
                    if(Roles.Contains(field.Name)) {
                        var path=Reference(field.Value);
                        if(path is not null)requested.Add((path,field.Name));
                    }
                    Find(field.Value);
                }
            } else if(value.ValueKind==JsonValueKind.Array)foreach(var child in value.EnumerateArray())Find(child);
        }
        foreach(var relative in packages.Values.Distinct().ToArray()) {
            using var document=JsonDocument.Parse(File.ReadAllText(Path.Combine(output,relative)));
            Find(document.RootElement);
        }
        if(requested.Count>256)throw new InvalidDataException("Exposure resource reference limit exceeded");
        var resources=new List<object>();var failures=new List<object>();
        var decode=cache.GetType().GetMethod("Texture",[typeof(string)])
            ??throw new MissingMethodException("TextureCache.Texture(string)");
        foreach(var (path,role) in requested.OrderBy(r=>r.path).ThenBy(r=>r.role))try {
            var relative=dump(Package(path));var file=Path.Combine(output,relative);
            using var document=JsonDocument.Parse(File.ReadAllText(file));
            var expected=role=="AutoExposureMeterMask"?"Texture2D":"CurveFloat";
            var name=path.Split('.').Last();
            var candidates=document.RootElement.EnumerateArray().Where(row=>
                row.TryGetProperty("type",out var type)&&type.GetString()==expected&&
                row.TryGetProperty("name",out var n)&&n.GetString()==name).ToArray();
            if(candidates.Length!=1)throw new InvalidDataException("Referenced exposure resource is absent or ambiguous in package");
            var value=candidates[0].GetProperty("value");
            var properties=value.TryGetProperty("Properties",out var p)?p.Clone():JsonSerializer.SerializeToElement(new{});
            if(expected=="CurveFloat") {
                if(!properties.TryGetProperty("FloatCurve",out var curve)||!curve.TryGetProperty("Keys",out var keys)||keys.GetArrayLength()==0)
                    throw new InvalidDataException("Referenced exposure curve has no serialized keys");
                resources.Add(new {source_path=path,role,kind="curve",raw=relative,raw_sha256=Hash(file),properties});
            } else {
                var result=decode.Invoke(cache,[path])??throw new InvalidDataException("Exposure meter texture decoder returned no image");
                var texture=JsonSerializer.SerializeToElement(result,result.GetType());
                var textureRelative=texture.GetProperty("RelativePath").GetString()!;
                var textureFile=Path.GetFullPath(Path.Combine(output,textureRelative));
                var root=Path.GetFullPath(output).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
                if(!textureFile.StartsWith(root,StringComparison.OrdinalIgnoreCase)||!File.Exists(textureFile))
                    throw new InvalidDataException("Exposure meter output is outside the resource directory or missing");
                resources.Add(new {source_path=path,role,kind="texture",raw=relative,raw_sha256=Hash(file),
                    properties,texture,texture_sha256=Hash(textureFile)});
            }
        }catch(Exception error)when(!EnvironmentState.IsResourceFailure(error)) {
            failures.Add(new{source_path=path,role,error=error.GetBaseException().Message});
        }
        File.WriteAllText(Path.Combine(output,"exposure-resources.json"),JsonSerializer.Serialize(new {
            schema=1,resources,failures,requested_count=requested.Count,
            scope="Explicit authored exposure curve and meter references; no substitute asset selection"
        },new JsonSerializerOptions{WriteIndented=true}));
        Console.WriteLine($"[state] exposure: {resources.Count} referenced resources; {failures.Count} unavailable resources");
    }
}
