using System.Collections;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;

internal static class EnvironmentState {
    internal static string CanonicalPath(string path) {
        var p=path.Replace('\\','/');
        if(p.StartsWith("/Game/",StringComparison.OrdinalIgnoreCase))return "DeltaForce/Content/"+p[6..];
        if(p.StartsWith("/Engine/",StringComparison.OrdinalIgnoreCase))return "Engine/Content/"+p[8..];
        return p;
    }
    internal static bool IsResourceFailure(Exception error) {
        var cause=error.GetBaseException();return cause is OutOfMemoryException || (cause.HResult&0xffff) is 8 or 14 or 39 or 112 or 1450 or 1455;
    }
    static string Identity(string path) => Convert.ToHexStringLower(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(path)))[..20];
    static object? Member(object obj,string name) => obj.GetType().GetProperty(name)?.GetValue(obj) ?? obj.GetType().GetField(name)?.GetValue(obj);
    public static void Export(object provider,object cache,string output,string mapRoot,
        Dictionary<string,string> packages,Func<string,string> dump) {
        var failures=new List<object>();var skies=new List<object>();
        var references=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        var environmentPackages=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var materialPaths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var unavailable=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        bool Relevant(string text) => new[]{"Sky","Weather","Environment","WorldSettings","ReflectionCapture","Ambient"}.Any(k=>text.Contains(k,StringComparison.OrdinalIgnoreCase));
        string Package(string path) => CanonicalPath(path).Split('.')[0];
        void Refs(JsonElement value,string role) {
            if(value.ValueKind==JsonValueKind.Object) {
                if(value.TryGetProperty("ObjectPath",out var path)&&path.ValueKind==JsonValueKind.String) {
                    var p=CanonicalPath(path.GetString()!);var label=value.TryGetProperty("ObjectName",out var n)?n.GetString()??"":"";
                    if(label.Contains("TextureCube")) {
                        var objectName=label.Split('\'').ElementAtOrDefault(1)?.Split(':').Last().Split('.').Last();
                        references[Package(p)+"."+(objectName??p.Split('.').Last())]=role;
                    }
                    else if(Relevant(p)&&label.Contains("Material"))materialPaths.Add(Package(p));
                    else if(Relevant(p)&&!label.Contains("Texture")&&!p.StartsWith("/Script/"))environmentPackages.Add(Package(p));
                }
                if(value.TryGetProperty("AssetPathName",out var soft)&&soft.ValueKind==JsonValueKind.String&&Relevant(soft.GetString()??"")&&!soft.GetString()!.StartsWith("/Script/"))
                    environmentPackages.Add(Package(soft.GetString()!));
                foreach(var item in value.EnumerateObject())Refs(item.Value,role);
            } else if(value.ValueKind==JsonValueKind.Array)foreach(var item in value.EnumerateArray())Refs(item,role);
        }
        for(int depth=0;depth<8;depth++) {
            foreach(var file in packages.Values.ToArray()) {
                using var rowsDocument=JsonDocument.Parse(File.ReadAllText(Path.Combine(output,file)));
                var rows=rowsDocument.RootElement;
                foreach(var obj in rows.EnumerateArray()) {
                    var label=obj.TryGetProperty("type",out var type)?type.GetString()??"":"";
                    if(obj.TryGetProperty("name",out var name))label+=" "+name.GetString();
                    if(obj.TryGetProperty("value",out var value)&&value.TryGetProperty("Outer",out var outer))label+=" "+outer.ToString();
                    if(Relevant(label))Refs(obj,label);
                }
            }
            var wanted=environmentPackages.Where(p=>!packages.ContainsKey(p)&&!unavailable.Contains(p)).Take(128).ToArray();
            if(wanted.Length==0)break;
            foreach(var path in wanted)try{dump(path);}catch(Exception e)when(!IsResourceFailure(e)){failures.Add(new{source=path,error=e.GetBaseException().Message});unavailable.Add(path);}
        }
        var map=mapRoot.Split(" + ").Last().TrimEnd('/').Split('/').Last();
        var files=(IEnumerable)(Member(provider,"Files")??throw new InvalidDataException("Missing provider files"));
        var named=new List<string>();
        foreach(var entry in files) {
            var path=(string)Member(entry!,"Key")!;
            if(path.EndsWith(".uasset",StringComparison.OrdinalIgnoreCase)&&path.Contains("/SkyCube/Mat/",StringComparison.OrdinalIgnoreCase)
                &&Path.GetFileNameWithoutExtension(path).Contains("_"+map+"_",StringComparison.OrdinalIgnoreCase))named.Add(path[..^7]);
        }
        // A map-library match is explicit evidence, separate from an actor
        // reference. Multiple candidates are retained without guessing one.
        foreach(var p in named)materialPaths.Add(p);
        var resolve=cache.GetType().GetMethod("Material")!;
        var decode=cache.GetType().GetMethod("Texture")!;
        foreach(var path in materialPaths.Order())try {
            var info=resolve.Invoke(cache,[path])!;
            var data=JsonSerializer.SerializeToElement(info,info.GetType());
            var textures=data.GetProperty("TextureParameters").EnumerateObject()
                .Where(p=>p.Name.Contains("Texture",StringComparison.OrdinalIgnoreCase)||p.Name.Contains("Sky",StringComparison.OrdinalIgnoreCase)||p.Name.Contains("Cube",StringComparison.OrdinalIgnoreCase)).ToArray();
            var skyTextures=textures.Where(p=>new[]{"Sky","Cube","HDRI","Environment"}.Any(k=>p.Name.Contains(k,StringComparison.OrdinalIgnoreCase))).ToArray();
            if(skyTextures.Length==1)textures=skyTextures;
            if(textures.Length!=1)continue;
            var texture=textures[0].Value.GetString()!;
            var master=data.GetProperty("MasterPath").GetString()??"";
            var spherical=new[]{"SkySphere","SkyBox","SkyDome","HDRI"}.Any(k=>master.Contains(k,StringComparison.OrdinalIgnoreCase))&&!master.Contains("Billboard",StringComparison.OrdinalIgnoreCase);
            var result=decode.Invoke(cache,[texture]);
            if(result is null){references[texture]=spherical?"sky_material_cube":"unverified_material_cube";continue;}
            var file=JsonSerializer.SerializeToElement(result,result.GetType());
            var textureRaw=dump(Package(texture));dump(path);
            using var textureDocument=JsonDocument.Parse(File.ReadAllText(Path.Combine(output,textureRaw)));
            var objects=textureDocument.RootElement;
            var tex=objects.EnumerateArray().First(o=>o.TryGetProperty("type",out var t)&&t.GetString()=="Texture2D").GetProperty("value");
            var props=tex.TryGetProperty("Properties",out var tp)?tp:default;
            var srgb=props.ValueKind!=JsonValueKind.Object||!props.TryGetProperty("SRGB",out var s)||s.GetBoolean();
            var rgbm=props.ValueKind==JsonValueKind.Object&&props.TryGetProperty("CompressionSettings",out var c)&&c.GetString()=="TC_HDR_RGBM";
            skies.Add(new{source_material=path,source_texture=texture,kind=spherical?"latlong":"reference_image",texture=file,
                parameters=data,srgb,rgbm,selection_basis=named.Contains(path)?"map_named_library":"source_reference",
                eligible=spherical&&!rgbm&&!named.Contains(path)&&file.GetProperty("Width").GetInt32()==file.GetProperty("Height").GetInt32()*2});
        }catch(Exception e)when(!IsResourceFailure(e)){failures.Add(new{source=path,error=e.GetBaseException().Message});}
        foreach(var (path,basis) in references)try {
            // Preserve all six original compressed faces; PNG conversion would
            // clamp HDR energy and lose the source cubemap face ordering.
            var method=provider.GetType().GetMethods().First(m=>m.Name=="LoadPackageObject"&&!m.IsGenericMethod&&m.GetParameters().Length==1&&m.GetParameters()[0].ParameterType==typeof(string));
            var obj=method.Invoke(provider,[path])!;
            if(!obj.GetType().Name.Contains("TextureCube"))continue;
            var mip=obj.GetType().GetMethod("GetFirstMip")!.Invoke(obj,null)??throw new InvalidDataException("Cooked cube mip unavailable");
            var w=Convert.ToInt32(Member(mip,"SizeX"));var h=Convert.ToInt32(Member(mip,"SizeY"));
            var bytes=(byte[])Member(Member(mip,"BulkData")!,"Data")!;
            var format=Member(obj,"Format")?.ToString()??Member(Member(obj,"PlatformData")!,"PixelFormat")?.ToString();
            var dxgi=format switch {"PF_BC6H"=>95,"PF_BC7"=>98,"PF_DXT1"=>71,"PF_DXT5"=>77,"PF_FloatRGBA"=>10,"PF_B8G8R8A8"=>87,_=>0};
            var faceBytes=format switch {"PF_BC6H" or "PF_BC7" or "PF_DXT5"=>((w+3)/4)*((h+3)/4)*16,"PF_DXT1"=>((w+3)/4)*((h+3)/4)*8,"PF_FloatRGBA"=>w*h*8,_=>w*h*4};
            if(w!=h||w<=0||w>4096||dxgi==0||bytes.Length!=faceBytes*6)throw new InvalidDataException($"Unsupported source cube layout {format} {w}x{h}, {bytes.Length} bytes");
            var relative="environment/"+Identity(path)+".dds";var full=Path.Combine(output,relative);Directory.CreateDirectory(Path.GetDirectoryName(full)!);
            if(format=="PF_BC6H")HdrCube.WriteDds(full,HdrCube.Decode(bytes,w),w);
            else using(var writer=new BinaryWriter(File.Create(full))) {
                writer.Write(new byte[]{68,68,83,32});writer.Write(124);writer.Write(0x100f);writer.Write(h);writer.Write(w);writer.Write(faceBytes);writer.Write(0);writer.Write(1);writer.Write(new byte[44]);
                foreach(var v in new[]{32,4,0x30315844,0,0,0,0,0,0x1008,0xfe00,0,0,0,dxgi,3,4,1,0})writer.Write(v);
                writer.Write(bytes);
            }
            dump(Package(path));
            skies.Add(new{source_texture=path,kind="cube",texture=new{RelativePath=relative,Width=w,Height=h},selection_basis=basis,
                eligible=basis.Contains("Sky",StringComparison.OrdinalIgnoreCase)&&!basis.Contains("unverified")});
        }catch(Exception e)when(!IsResourceFailure(e)){failures.Add(new{source=path,error=e.GetBaseException().Message});}
        File.WriteAllText(Path.Combine(output,"environment.json"),JsonSerializer.Serialize(new{schema=1,mapRoot,skies,failures},new JsonSerializerOptions{WriteIndented=true}));
        Console.WriteLine($"[state] environment: {skies.Count} source textures; {failures.Count} unavailable resources");
        ExposureState.Export(cache,output,packages,dump);
    }
}
