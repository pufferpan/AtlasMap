using Dfmap;
using Newtonsoft.Json;
using CUE4Parse.UE4.Assets.Exports.Component;
using CUE4Parse.UE4.Assets.Exports.Component.StaticMesh;
using CUE4Parse.UE4.Objects.Core.Math;

var output = args[1];
Directory.CreateDirectory(output);
DeltaForceTypes.Register();
if (args.Contains("--buffers"))
{
    foreach(var path in args.Skip(3))
    {
        var bytes = File.ReadAllBytes(path);
        var count = BitConverter.ToInt32(bytes,6);
        using var ar = new CUE4Parse.UE4.Readers.FByteArchive(path,bytes,
            new CUE4Parse.UE4.Versions.VersionContainer(CUE4Parse.UE4.Versions.EGame.GAME_DeltaForce));
        ar.Position=18+count*12;
        try
        {
            var vertex = new CUE4Parse.UE4.Assets.Exports.StaticMesh.FStaticMeshVertexBuffer(ar);
            Console.WriteLine(JsonConvert.SerializeObject(new {path,count,vertex.NumVertices,vertex.NumTexCoords,end=ar.Position,first=vertex.UV.Take(2)},Formatting.Indented));
        }
        catch(Exception ex) { Console.WriteLine($"{path} offset {ar.Position}: {ex}"); }
    }
    return;
}
var probes = new List<object>();
foreach (var rotation in new[] { new FRotator(0,90,0), new FRotator(25,-38,17), new FRotator(-15,0,70) })
{
    var transform = new FTransform(rotation, new FVector(100,200,300), new FVector(2,3,4));
    probes.Add(Check("synthetic", "basis", "", transform));
}
var cfg = JsonConvert.DeserializeObject<GameConfig>(File.ReadAllText(args[0]));
CUE4Parse.Compression.OodleHelper.Initialize(Path.GetFullPath("oodle-data-shared.dll"));
using var provider = Mount.Create(cfg, AesKeySet.Load(cfg.KeyFile));
if(args.Contains("--rvt-layers"))
{
    RuntimeTextureLayers.Build(provider,output,args[3],int.Parse(args[4]));
    return;
}
if(args.Contains("--texture-files"))
{
    CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(Path.GetFullPath("Detex.dll"));
    CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(Path.GetFullPath("Detex.dll"));
    CUE4Parse.Compression.ZlibHelper.Initialize(Path.GetFullPath("zlib-ng2.dll"));
    var textures=new TextureCache(provider,output,"textures",int.Parse(args[3]));
    var rows=args.Skip(4).Select(path=>new{source=path,texture=textures.Texture(path)}).ToList();
    File.WriteAllText(Path.Combine(output,"texture_files.json"),JsonConvert.SerializeObject(new{textures=rows,textures.Failures,textures.MissReasons},Formatting.Indented));
    return;
}
if(args.Contains("--dump-many"))
{
    foreach(var path in File.ReadAllLines(args[3]).Where(x=>!string.IsNullOrWhiteSpace(x)))
        Inspect.CmdDump(provider,path,Path.Combine(output,MeshCache.SplitObjectPath(path).Object+".json"));
    return;
}
if(args.Contains("--attributes"))
{
    AttributeBundle.Build(provider,output,args[3]);
    return;
}
if(args.Contains("--uv-smoke"))
{
    var cache=new MeshCache(provider);
    var writer=new GlbWriter();
    foreach(var path in args.Skip(3))
    {
        var mesh=cache.Get(path)??throw new InvalidDataException("Cannot load UV smoke-test mesh: "+path);
        writer.AddInstance(writer.AddMesh(mesh),new float[3],new float[3],new[]{1f,1f,1f},mesh.Path);
    }
    writer.Write(Path.Combine(output,"uv_smoke.glb"),"Authored UV validation");
    return;
}
if(args.Contains("--ground-export"))
{
    GroundExport.Build(provider,output,args[3]);
    return;
}
if(args.Contains("--material-refresh"))
{
    MaterialRefresh.Build(provider,output,args[3]);
    return;
}
if(args.Contains("--vt-compat"))
{
    CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(Path.GetFullPath("Detex.dll"));
    CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(Path.GetFullPath("Detex.dll"));
    CUE4Parse.Compression.ZlibHelper.Initialize(Path.GetFullPath("zlib-ng2.dll"));
    foreach(var path in args.Skip(3))
    {
        var texture=provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>(path);
        var ok=VirtualTextureCompat.Repair(texture,out var reason);
        Console.WriteLine($"{path}: {ok} {reason}");
        if(!ok)continue;
        Console.WriteLine(JsonConvert.SerializeObject(texture.PlatformData.VTData.Chunks.Select(c=>new {c.SizeInBytes,c.CodecType,c.CodecPayloadOffset,c.BulkData.Header}),Formatting.Indented));
        try
        {
            var decoded=CUE4Parse_Conversion.Textures.TextureDecoder.Decode(texture);
            var filename=Path.Combine(output,MeshCache.SplitObjectPath(path).Object+"_vt.png");
            MapImage.WritePng(filename,decoded.Data,decoded.Width,decoded.Height);
            Console.WriteLine($"Decoded {decoded.Width}x{decoded.Height} {decoded.PixelFormat} -> {filename}");
        }
        catch(Exception ex){Console.WriteLine(ex);}
    }
    return;
}
if(args.Contains("--archive-info"))
{
    var texture=provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>(args[3]);
    var owner=texture.Owner;
    var flags=System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.NonPublic;
    Console.WriteLine(owner.GetType().FullName);
    Console.WriteLine(string.Join("\n",owner.GetType().GetFields(flags).Select(f=>$"FIELD {f.Name}: {f.FieldType.FullName}")));
    Console.WriteLine(string.Join("\n",owner.GetType().GetProperties(flags).Select(p=>$"PROP {p.Name}: {p.PropertyType.FullName}")));
    foreach(var f in owner.GetType().GetFields(flags))
        if(typeof(CUE4Parse.UE4.Readers.FArchive).IsAssignableFrom(f.FieldType))
        {
            var ar=f.GetValue(owner) as CUE4Parse.UE4.Readers.FArchive;
            Console.WriteLine($"field {f.Name}: {f.FieldType} name={ar?.Name} length={ar?.Length} position={ar?.Position}");
        }
    foreach(var p in owner.GetType().GetProperties(flags))
        if(typeof(CUE4Parse.UE4.Readers.FArchive).IsAssignableFrom(p.PropertyType))
        {
            var ar=p.GetValue(owner) as CUE4Parse.UE4.Readers.FArchive;
            Console.WriteLine($"property {p.Name}: {p.PropertyType} name={ar?.Name} length={ar?.Length} position={ar?.Position}");
        }
    var vt=texture.PlatformData.VTData;
    for(var type=vt.Chunks[0].BulkData.GetType();type is not null;type=type.BaseType)
        foreach(var f in type.GetFields(flags|System.Reflection.BindingFlags.DeclaredOnly))
            Console.WriteLine($"BULK {type.Name}.{f.Name}: {f.FieldType.FullName} valueType={f.GetValue(vt.Chunks[0].BulkData)?.GetType().FullName}");
    Console.WriteLine(JsonConvert.SerializeObject(new {vt.Width,vt.Height,vt.NumLayers,vt.NumMips,chunks=vt.Chunks.Select(c=>new {c.SizeInBytes,c.CodecPayloadSize,c.CodecPayloadOffset,c.CodecType,c.BulkData.Header})},Formatting.Indented));
    return;
}
if(args.Contains("--visibility"))
{
    var items=Newtonsoft.Json.Linq.JArray.Parse(File.ReadAllText(args[3]));
    var rows=new List<object>();
    foreach(var group in items.GroupBy(x=>x.Value<string>("source_level")))
    {
        var pkg=provider.LoadPackage(group.Key);
        var objects=new List<CUE4Parse.UE4.Assets.Exports.UObject>();
        foreach(var lazy in pkg.ExportsLazy)try{if(lazy.Value is {} obj)objects.Add(obj);}catch{}
        var byPath=objects.ToDictionary(x=>x.GetPathName(),x=>x);
        var components=objects.OfType<USceneComponent>().ToDictionary(x=>(x.Outer?.ToString()??"")+"/"+x.Name,x=>x);
        foreach(var item in group)
        {
            var key=item.Value<string>("Actor")+"/"+item.Value<string>("Component");
            if(!components.TryGetValue(key,out var comp))continue;
            var ownerText=comp.Outer?.ToString()??"";
            var quote=ownerText.IndexOf('\'');
            var ownerPath=quote>=0?ownerText[(quote+1)..].TrimEnd('\''):ownerText;
            byPath.TryGetValue(ownerPath,out var owner);
            var hidden=Flag(comp,"bHiddenInGame");
            var visible=Flag(comp,"bVisible");
            var ownerHidden=owner is null?null:Flag(owner,"bHidden");
            var editorOnly=owner is null?null:Flag(owner,"bIsEditorOnlyActor");
            rows.Add(new {source_level=group.Key,asset=item.Value<string>("Mesh"),loc=item["Loc"],component=comp.GetPathName(),
                hidden_in_game=hidden,visible,owner_hidden=ownerHidden,editor_only=editorOnly,
                renderable=hidden!=true&&visible!=false&&ownerHidden!=true&&editorOnly!=true});
        }
    }
    File.WriteAllText(Path.Combine(output,"visibility_audit.json"),JsonConvert.SerializeObject(rows,Formatting.Indented));
    Console.WriteLine($"Visibility checked: {rows.Count}");
    return;
}
if(args.Contains("--repair-bundle"))
{
    RepairBundle.Build(provider,output,args[3],args[4]);
    return;
}
if(args.Contains("--sections"))
{
    var cache=new MeshCache(provider);
    foreach(var path in args.Skip(3))
    {
        var mesh=cache.Get(path);
        if(mesh is null) {Console.WriteLine($"Cannot decode {path}");continue;}
        var table=MeshSections.Find(provider,mesh);
        var report=new {path,mesh.VertexCount,mesh.TriangleCount,materials=mesh.Materials,offset=table?.Offset,
            sections=table?.Sections.Select(s=>new {s.MaterialIndex,s.FirstIndex,s.NumTriangles,s.MinVertexIndex,s.MaxVertexIndex})};
        File.WriteAllText(Path.Combine(output,MeshCache.SplitObjectPath(path).Object+"_sections.json"),JsonConvert.SerializeObject(report,Formatting.Indented));
        Console.WriteLine(JsonConvert.SerializeObject(report,Formatting.Indented));
    }
    return;
}
if (args.Contains("--inventory"))
{
    var prefixes=args[3].Split(',',StringSplitOptions.RemoveEmptyEntries);
    var paths=provider.Files.Keys.Where(p=>p.EndsWith(".umap",StringComparison.OrdinalIgnoreCase)
        && prefixes.Any(prefix=>p.StartsWith(prefix,StringComparison.OrdinalIgnoreCase))).Order().ToList();
    var levels=new List<LevelSummary>();
    foreach(var path in paths)
    {
        try { levels.Add(Levels.Extract(provider,path,includeHidden:true)); }
        catch(Exception ex) { levels.Add(new LevelSummary {Level=path,Errors={ex.ToString()}}); }
        if(levels.Count%25==0 || levels.Count==paths.Count) Console.WriteLine($"inventory {levels.Count}/{paths.Count}; instances {levels.Sum(l=>l.InstanceCount)}");
    }
    File.WriteAllText(Path.Combine(output,"level_inventory.json"),JsonConvert.SerializeObject(levels,Formatting.Indented));
    return;
}
if (args.Contains("--vt"))
{
    foreach(var path in args.Skip(3))
    {
        var texture = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>(path);
        var vt = texture.PlatformData.VTData;
        Console.WriteLine(JsonConvert.SerializeObject(new {path,texture.Format,vt.Width,vt.Height,vt.NumMips,vt.NumLayers,vt.TileSize,vt.TileBorderSize,vt.LayerTypes,legacy=vt.IsLegacyData(),chunks=vt.Chunks.Select(c=>new {c.SizeInBytes,c.CodecType,bulkSize=c.BulkData.GetDataSize(),c.BulkData.Header})},Formatting.Indented));
        for(var mip=0;mip<vt.NumMips;mip++)
        {
            var tile = vt.GetTileData(mip,0,0);
            Console.WriteLine($"mip {mip}: {tile}");
        }
    }
    return;
}
var results = new List<object>();
foreach (var path in args.Skip(2))
{
    var package = provider.LoadPackage(path);
    foreach (var export in package.ExportsLazy)
    {
        try
        {
            if (export.Value is not UStaticMeshComponent comp) continue;
            var mesh = comp.GetLoadedStaticMesh();
            if (mesh is null) continue;
            var transform = comp.GetAbsoluteTransform();
            results.Add(Check(path, comp.GetPathName(), mesh.GetPathName(), transform));
        }
        catch(Exception ex) { Console.WriteLine(ex.Message); }
    }
}
File.WriteAllText(Path.Combine(output,"native_transform_audit.json"), JsonConvert.SerializeObject(new {probes, instances=results}, Formatting.Indented));
Console.WriteLine($"Audited {results.Count} native component transforms.");

static object Check(string level, string component, string mesh, FTransform transform)
{
    var rotation = transform.Rotation.Rotator();
    var loc = transform.Translation;
    var scale = transform.Scale3D;
    var matrix = GlbWriter.BuildNodeMatrix(new[]{loc.X,loc.Y,loc.Z}, new[]{rotation.Roll,rotation.Pitch,rotation.Yaw},new[]{scale.X,scale.Y,scale.Z});
    var maxDelta = 0.0;
    var maxNativeDelta = 0.0;
    var nativeMatrix = GlbWriter.ConvertNativeMatrix(Levels.NativeMatrix(transform));
    var axes = new[] { new FVector(100,0,0), new FVector(0,100,0),new FVector(0,0,100),new FVector(1000,2000,3000) };
    foreach(var axis in axes)
    {
        var expected = transform.TransformPosition(axis);
        var input = new[]{axis.X*0.01,axis.Z*0.01,axis.Y*0.01};
        var actual = new double[3];
        for(var r=0;r<3;r++) actual[r]=matrix[r]*input[0]+matrix[4+r]*input[1]+matrix[8+r]*input[2]+matrix[12+r];
        maxDelta=Math.Max(maxDelta, Math.Sqrt(Math.Pow(actual[0]-expected.X*.01,2)+Math.Pow(actual[1]-expected.Z*.01,2)+Math.Pow(actual[2]-expected.Y*.01,2)));
        for(var r=0;r<3;r++) actual[r]=nativeMatrix[r]*input[0]+nativeMatrix[4+r]*input[1]+nativeMatrix[8+r]*input[2]+nativeMatrix[12+r];
        maxNativeDelta=Math.Max(maxNativeDelta, Math.Sqrt(Math.Pow(actual[0]-expected.X*.01,2)+Math.Pow(actual[1]-expected.Z*.01,2)+Math.Pow(actual[2]-expected.Y*.01,2)));
    }
    var x = transform.TransformVector(new FVector(1,0,0));
    var y = transform.TransformVector(new FVector(0,1,0));
    var z = transform.TransformVector(new FVector(0,0,1));
    return new {level,component,mesh,loc=new[]{loc.X,loc.Y,loc.Z},rot=new[]{rotation.Roll,rotation.Pitch,rotation.Yaw},scale=new[]{scale.X,scale.Y,scale.Z},
        nativeQuat = new[]{transform.Rotation.X,transform.Rotation.Y,transform.Rotation.Z,transform.Rotation.W},
        nativeUEColumnMatrix = new[]{new[]{x.X,y.X,z.X,loc.X},new[]{x.Y,y.Y,z.Y,loc.Y},new[]{x.Z,y.Z,z.Z,loc.Z},new[]{0f,0f,0f,1f}},
        exportedProbeErrorM=maxDelta, nativeMatrixProbeErrorM=maxNativeDelta, matrixUE=Levels.NativeMatrix(transform)};
}

static bool? Flag(CUE4Parse.UE4.Assets.Exports.UObject obj,string name)
{
    if(obj.Properties?.Any(p=>p.Name.Text==name)!=true)return null;
    return obj.GetOrDefault<bool>(name);
}
