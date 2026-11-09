using System.Text.Json;

internal sealed record MaterialSourceIssue(string source,string reference,string reason,string message);
internal sealed record MaterialSourceResult(List<JsonElement> chain,string status,List<MaterialSourceIssue> issues);

internal static class MaterialSources {
    internal static bool IsPackageReference(string? path) {
        if(string.IsNullOrWhiteSpace(path))return false;
        var p=path.Replace('\\','/');
        if(p.Contains('\0')||p.Split('/').Any(part=>part is "." or ".."))return false;
        return p.StartsWith("DeltaForce/Content/",StringComparison.OrdinalIgnoreCase)
            ||p.StartsWith("Engine/Content/",StringComparison.OrdinalIgnoreCase)
            ||(p.StartsWith('/')&&p.IndexOf('/',1)>1&&!p.StartsWith("/Script/",StringComparison.OrdinalIgnoreCase));
    }

    // Only absent optional material references degrade to the glTF shader.
    // IO, malformed JSON, resource exhaustion and mandatory level reads stay fatal.
    internal static MaterialSourceResult Read(string path,Func<string,JsonDocument> load) {
        var chain=new List<JsonElement>();var issues=new List<MaterialSourceIssue>();
        var visited=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var current=path;
        MaterialSourceResult Stop(string reason,string message) {
            issues.Add(new(path,current,reason,message));
            return new(chain,reason,issues);
        }
        for(int depth=0;depth<16;depth++) {
            if(!IsPackageReference(current))
                return Stop(chain.Count==0?"placeholder":"invalid_parent","Not a cooked package reference; preserve the existing glTF material slot.");
            var package=current.Replace('\\','/').Split('.')[0];
            if(!visited.Add(package))return Stop("parent_cycle","Repeated package in material inheritance.");
            JsonDocument document;
            try {document=load(package);}
            catch(Exception error)when(error.GetBaseException() is KeyNotFoundException) {
                return Stop(chain.Count==0?"missing_source":"missing_parent",error.GetBaseException().Message);
            }
            using(document) {
                var source=document.RootElement.EnumerateArray().FirstOrDefault(o=>
                    o.TryGetProperty("type",out var type)&&type.ValueKind==JsonValueKind.String
                    &&(type.GetString()=="Material"||type.GetString()!.Contains("MaterialInstance"))
                    &&o.TryGetProperty("value",out var value)&&value.ValueKind==JsonValueKind.Object);
                if(source.ValueKind==JsonValueKind.Undefined)
                    return Stop("no_material_export","Package has no readable native material export; preserve the glTF shader.");
                chain.Add(source.Clone());
                if(!source.GetProperty("value").TryGetProperty("Properties",out var props))
                    return new(chain,"complete",issues);
                if(props.ValueKind!=JsonValueKind.Object)
                    return Stop("unreadable_properties","Native material properties are not an object.");
                if(!props.TryGetProperty("Parent",out var parent)||parent.ValueKind==JsonValueKind.Null)
                    return new(chain,"complete",issues);
                if(parent.ValueKind!=JsonValueKind.Object||!parent.TryGetProperty("ObjectPath",out var parentPath)
                    ||parentPath.ValueKind!=JsonValueKind.String||string.IsNullOrWhiteSpace(parentPath.GetString()))
                    return Stop("invalid_parent","Native parent does not contain a package object path.");
                current=parentPath.GetString()!;
            }
        }
        return Stop("parent_depth_limit","Material inheritance exceeds 16 packages.");
    }
}
