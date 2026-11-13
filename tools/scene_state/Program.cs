// Uses the user's exact, unmodified dfmap assembly and its public embedding API.
using System.Collections;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Text.Json;

Console.OutputEncoding = new System.Text.UTF8Encoding(false);
Console.SetError(new StreamWriter(Console.OpenStandardError(),new System.Text.UTF8Encoding(false)){AutoFlush=true});
var exportChunk = args.Length == 5 && args[0] == "--export-chunk";
var scanChunk = args.Length == 5 && args[0] == "--scan-chunk";
var environmentOnly = args.Length == 5 && args[0] == "--environment-only";
var reflectionOnly = args.Length == 5 && args[0] == "--reflection-only";
var runtimeOnly = args.Length == 5 && args[0] == "--check-runtime";
if (exportChunk || scanChunk || environmentOnly || reflectionOnly || runtimeOnly) args = args[1..];
if (args.Length != 4) throw new ArgumentException("scene-state [--export-chunk] <dfmap-dir> <config> <map-export|argument-json> <output>");
var reference = Path.GetFullPath(args[0]);
var root = Path.GetFullPath(args[2]);
var output = Path.GetFullPath(args[3]);
Directory.CreateDirectory(output);
if (!exportChunk && !scanChunk && !environmentOnly && !reflectionOnly && !runtimeOnly)
    File.WriteAllText(Path.Combine(output,"state-index.json"),"{\"complete\":false}");
var expected = "23642525d210d158cb6a57ffd6e3258e6e5fbbb6d4cb2dbfd91c6f3376b3f103";
var binary = Path.Combine(reference, "dfmap.dll");
string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
if (Hash(File.ReadAllBytes(binary)) != expected) throw new InvalidDataException("dfmap.dll differs from the required exporter");
Directory.SetCurrentDirectory(reference);
RuntimeDependencies.Install(reference);
var asm = AssemblyLoadContext.Default.LoadFromAssemblyPath(binary);
var program = asm.GetType("Dfmap.Program", true)!;
asm.GetType("Dfmap.DeltaForceTypes", true)!.GetMethod("Register")!.Invoke(null, null);
CUE4Parse.UE4.Assets.ObjectTypeRegistry.RegisterClass("TextureCube",typeof(DeltaForceTextureCube));
object? provider = null;
try {
    if(runtimeOnly){Console.WriteLine("[runtime] exporter dependencies ready");return;}
    if(reflectionOnly){HdrCube.ExportLegacy(output);return;}
    program.GetMethod("UseConfigFile")!.Invoke(null, [Path.GetFullPath(args[1]), false]);
    provider = program.GetMethod("SharedProvider")!.Invoke(null, null)!;
    if (scanChunk) {
        var paths=JsonSerializer.Deserialize<string[]>(File.ReadAllText(root))!;
        var method=asm.GetType("Dfmap.Levels",true)!.GetMethod("Extract")!;
        var rows=new List<object>();
        foreach (var level in paths) {
            Console.WriteLine($"[scan] level {rows.Count+1}/{paths.Length}: {level}");
            var summary=method.Invoke(null,[provider,level,false,int.MaxValue,true])!;
            var kind=summary.GetType();
            var instances=(IEnumerable)kind.GetProperty("Instances")!.GetValue(summary)!;
            var meshes=instances.Cast<object>().Select(i=>(string)i.GetType().GetProperty("Mesh")!.GetValue(i)!)
                .Distinct(StringComparer.OrdinalIgnoreCase).Count();
            rows.Add(new { level, instances=(int)kind.GetProperty("InstanceCount")!.GetValue(summary)!,
                actors=(int)kind.GetProperty("ActorCount")!.GetValue(summary)!, meshes });
        }
        File.WriteAllText(Path.Combine(output,"scan.json"),JsonSerializer.Serialize(new { complete=true, levels=rows }));
        return;
    }
    if (exportChunk) {
        // Argument arrays in JSON avoid Windows' command-line length limit
        // for maps with thousands of source levels. Run the exact pinned
        // exporter's original merge code with the original argument array.
        var exportArgs = JsonSerializer.Deserialize<string[]>(File.ReadAllText(root))
                         ?? throw new InvalidDataException("Missing chunk arguments");
        if (exportArgs.Length < 2 || Path.GetFullPath(exportArgs[1]) != output)
            throw new InvalidDataException("Chunk output does not match argument plan");
        var merge = asm.GetType("Dfmap.Merge",true)!.GetMethod("CmdMerge")!;
        var code = (int)merge.Invoke(null, [provider, exportArgs])!;
        if (code != 0) throw new InvalidDataException($"Pinned exporter exited with {code}");
        return;
    }
    var dump = asm.GetType("Dfmap.Inspect", true)!.GetMethod("CmdDump")!;
    var extract = asm.GetType("Dfmap.Levels", true)!.GetMethod("Extract")!;
    using var reportDocument = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "merge_report.json")));
    var report = reportDocument.RootElement;
    var levels = report.GetProperty("Levels").EnumerateArray().Where(x => x.GetProperty("Include").GetBoolean())
        .Select(x => x.GetProperty("Level").GetString()!).ToArray();
    var rawdir = Path.Combine(output, "raw");
    Directory.CreateDirectory(rawdir);
    var packages = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
    string Dump(string package) {
        if (packages.TryGetValue(package, out var previous)) return previous;
        var file = Path.Combine(rawdir, Hash(System.Text.Encoding.UTF8.GetBytes(package))[..20]+".json");
        if ((int)dump.Invoke(null, [provider, package, file])! != 0) throw new InvalidDataException(package);
        packages.Add(package, Path.GetRelativePath(output, file).Replace('\\','/'));
        return packages[package];
    }
    if(environmentOnly) {
        // This mode deliberately skips the full geometry/state export, but it
        // still needs authored environment references. An empty package map
        // silently skipped the actual map sky and only tried library names.
        foreach(var level in levels.Where(p=>new[]{"TODLight","SkyLight","Environment","Lighting"}
            .Any(k=>p.Contains(k,StringComparison.OrdinalIgnoreCase))).Take(128))Dump(level);
        var envType=asm.GetType("Dfmap.TextureCache",true)!;
        var envCache=Activator.CreateInstance(envType,[provider,output,"textures",0])!;
        EnvironmentState.Export(provider,envCache,output,report.GetProperty("MapRoot").GetString()!,packages,Dump);
        return;
    }
    var summaries = new List<object>();
    foreach (var level in levels) {
        Console.WriteLine($"[state] level {summaries.Count+1}/{levels.Length}: {level}");
        var raw = Dump(level);
        var summary = extract.Invoke(null, [provider, level, false, int.MaxValue, true])!;
        var lights = summary.GetType().GetProperty("Lights")!.GetValue(summary)!;
        var json = JsonSerializer.SerializeToElement(lights, lights.GetType());
        summaries.Add(new { level, raw, lights = json });
    }
    // Resolve material inheritance through the pinned exporter, without changing
    // its geometry exporter. glTF loses native transparency and water settings.
    var materialPaths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    foreach(var glb in Directory.EnumerateFiles(Path.Combine(root,"split"),"*.glb",SearchOption.AllDirectories)) {
        using var stream=File.OpenRead(glb);using var reader=new BinaryReader(stream);
        reader.ReadBytes(12);var length=reader.ReadInt32();reader.ReadInt32();
        using var glbDocument=JsonDocument.Parse(reader.ReadBytes(length));
        var document=glbDocument.RootElement;
        if(document.TryGetProperty("materials",out var mats)) foreach(var mat in mats.EnumerateArray())
            if(mat.TryGetProperty("extras",out var extras)&&extras.ValueKind==JsonValueKind.Object&&extras.TryGetProperty("unrealMaterialPath",out var path)
                &&path.ValueKind==JsonValueKind.String&&!string.IsNullOrWhiteSpace(path.GetString())) materialPaths.Add(path.GetString()!);
    }
    var cacheType=asm.GetType("Dfmap.TextureCache",true)!;
    var materialCache=Activator.CreateInstance(cacheType,[provider,output,"textures",1024])!;
    var resolve=cacheType.GetMethod("Material")!;
    var materialRecords=new Dictionary<string,object>();
    var materialIssues=new List<MaterialSourceIssue>();
    foreach(var path in materialPaths) {
        var source=MaterialSources.Read(path,package=> {
            var file=Dump(package);
            return JsonDocument.Parse(File.ReadAllText(Path.Combine(output,file)));
        });
        var chain=source.chain;
        materialIssues.AddRange(source.issues);
        foreach(var issue in source.issues)
            Console.WriteLine($"[state] material fallback ({issue.reason}): {issue.source} -> {issue.reference}; {issue.message}");
        var info=chain.Count>0?resolve.Invoke(materialCache,[path]):null;
        var native=info is null?JsonSerializer.SerializeToElement(new { Path=path,MasterPath=(string?)null })
            :JsonSerializer.SerializeToElement(info,info.GetType());
        var textures=new Dictionary<string,object>();
        var master=native.GetProperty("MasterPath").GetString()??"";
        foreach(var key in master.Contains("Water",StringComparison.OrdinalIgnoreCase)||master.Contains("Ocean",StringComparison.OrdinalIgnoreCase)
                    ? new[]{"Normal"} : Array.Empty<string>()) {
            if(native.TryGetProperty(key,out var value)&&value.ValueKind==JsonValueKind.String) {
                var decoded=cacheType.GetMethod("Texture")!.Invoke(materialCache,[value.GetString()]);
                if(decoded is not null) textures[key]=JsonSerializer.SerializeToElement(decoded,decoded.GetType());
            }
        }
        materialRecords[path]=new { resolved=native, chain, textures,source_status=source.status,issues=source.issues };
        Console.WriteLine($"[state] material {materialRecords.Count}/{materialPaths.Count}: {path}");
    }
    File.WriteAllText(Path.Combine(output,"materials.json"),JsonSerializer.Serialize(materialRecords));
    File.WriteAllText(Path.Combine(output,"material-report.json"),JsonSerializer.Serialize(new {
        complete=true,materials=materialRecords.Count,fallbacks=materialIssues,
        policy="Preserve glTF geometry and material slots for placeholders or absent native material references." }));
    Console.WriteLine($"[state] material sources: {materialRecords.Count} materials, {materialIssues.Count} explicitly reported fallbacks");
    // Retain class-template defaults for native lights, fog, post-process and
    // game weather actors. Instance properties override these in the consumer.
    var relevant = new[] { "LightComponent", "HeightFog", "PostProcess", "Weather", "WorldSettings", "Sky", "ReflectionCapture", "Environment" };
    for (var depth=0; depth<8; depth++) {
        var wanted = new HashSet<string>();
        foreach (var file in packages.Values.ToArray()) {
            using var templateDocument = JsonDocument.Parse(File.ReadAllText(Path.Combine(output,file)));
            var data = templateDocument.RootElement;
            foreach (var obj in data.EnumerateArray()) {
                if (!obj.TryGetProperty("type", out var type) || !relevant.Any(k => type.GetString()!.Contains(k))) continue;
                if (!obj.TryGetProperty("value", out var value) || !value.TryGetProperty("Template", out var template)) continue;
                if (!template.TryGetProperty("ObjectPath", out var path)) continue;
                var package = path.GetString()!.Split('.')[0];
                if (package.StartsWith("/Script/") || packages.ContainsKey(package)) continue;
                wanted.Add(package);
            }
        }
        if (wanted.Count==0) break;
        foreach (var package in wanted) Dump(package);
    }
    var environmentCache=Activator.CreateInstance(cacheType,[provider,output,"textures",0])!;
    EnvironmentState.Export(provider,environmentCache,output,report.GetProperty("MapRoot").GetString()!,packages,Dump);
    // Preserve cooked bake payloads byte-for-byte, including optional mips.
    // These are source evidence, not a claim that stock UE can load custom PRT.
    var assets = new List<object>();
    var payloadPackages=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    void CollectPayloads(JsonElement value) {
        if (value.ValueKind==JsonValueKind.Object) {
            if (value.TryGetProperty("ObjectName",out var name) && value.TryGetProperty("ObjectPath",out var path)) {
                var label=name.GetString()??"";
                if (new[]{"PreBakeShadowDepthMap'","LocalLightBakeVolume'","LocalReflectionGroupBake'","TextureCube'","ReflectionCaptureData'"}.Any(k=>label.Contains(k)))
                    payloadPackages.Add(path.GetString()!.Split('.')[0]);
            }
            foreach (var item in value.EnumerateObject()) CollectPayloads(item.Value);
        } else if (value.ValueKind==JsonValueKind.Array) {
            foreach (var item in value.EnumerateArray()) CollectPayloads(item);
        }
    }
    foreach (var file in packages.Values) {
        using var payloadDocument=JsonDocument.Parse(File.ReadAllText(Path.Combine(output,file)));
        CollectPayloads(payloadDocument.RootElement);
    }
    var sourceRoot = report.GetProperty("MapRoot").GetString()!.Split(" + ");
    var fileMember = provider.GetType().GetProperty("Files")?.GetValue(provider)
                     ?? provider.GetType().GetField("Files")?.GetValue(provider)
                     ?? throw new MissingMemberException(provider.GetType().FullName,"Files");
    var files = (IEnumerable)fileMember;
    foreach (var item in files) {
        var itemType = item.GetType();
        var path = (string)itemType.GetProperty("Key")!.GetValue(item)!;
        var extensionOffset=path.LastIndexOf('.');
        bool referenced=extensionOffset>=0 && payloadPackages.Contains(path[..extensionOffset]);
        if (!referenced && !(sourceRoot.Any(p => path.StartsWith(p,StringComparison.OrdinalIgnoreCase))
            && path.Contains("/LightMapBakeLevel/",StringComparison.OrdinalIgnoreCase))) continue;
        var gamefile = itemType.GetProperty("Value")!.GetValue(item)!;
        var read = gamefile.GetType().GetMethods().FirstOrDefault(m=>m.Name=="Read"
            && m.ReturnType==typeof(byte[]) && m.GetParameters().All(p=>p.IsOptional));
        byte[] bytes;
        if (read is not null) {
            bytes=(byte[])read.Invoke(gamefile,read.GetParameters().Select(p=>p.DefaultValue).ToArray())!;
        } else {
            var extension=gamefile.GetType().Assembly.GetTypes().SelectMany(t=>t.GetMethods(BindingFlags.Public|BindingFlags.Static))
                .First(m=>m.Name=="Read" && m.ReturnType==typeof(byte[]) && m.GetParameters().Length>=1
                && m.GetParameters()[0].ParameterType.IsInstanceOfType(gamefile)
                && m.GetParameters().Skip(1).All(p=>p.IsOptional));
            bytes=(byte[])extension.Invoke(null,new object?[]{gamefile}.Concat(extension.GetParameters().Skip(1).Select(p=>p.DefaultValue)).ToArray())!;
        }
        var target = Path.GetFullPath(Path.Combine(output,"assets",path));
        var safeRoot = Path.Combine(output,"assets") + Path.DirectorySeparatorChar;
        if (!target.StartsWith(safeRoot,StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException(path);
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        var digest=Hash(bytes);
        var cache=Environment.GetEnvironmentVariable("ATLASMAP_BAKE_CACHE");
        if (!string.IsNullOrWhiteSpace(cache)) {
            Directory.CreateDirectory(cache);
            var shared=Path.Combine(cache,digest);
            if (!File.Exists(shared)) {
                var partial=shared+"."+Guid.NewGuid().ToString("N")+".partial";
                try {
                    File.WriteAllBytes(partial,bytes);
                    try { File.Move(partial,shared); }
                    catch (IOException) when (File.Exists(shared)) { }
                } finally { if (File.Exists(partial)) File.Delete(partial); }
            }
            if (!OperatingSystem.IsWindows() || !NativeLinks.CreateHardLink(target,shared,IntPtr.Zero))
                File.Copy(shared,target,true);
        } else File.WriteAllBytes(target,bytes);
        assets.Add(new { path, bytes=bytes.LongLength, sha256=digest });
        Console.WriteLine($"[state] preserved {path} ({bytes.Length} bytes)");
    }
    HdrCube.ExportLegacy(output,payloadPackages);
    var state = new { complete=true, schema=1, mapRoot=report.GetProperty("MapRoot").GetString(),
        exporter=new { directory=reference, sha256=expected, mvid=asm.ManifestModule.ModuleVersionId },
        levels=summaries, packages, preservedAssets=assets };
    File.WriteAllText(Path.Combine(output,"state-index.json"),JsonSerializer.Serialize(state,new JsonSerializerOptions { WriteIndented=true }));
    Console.WriteLine($"[state] complete: {levels.Length} levels, {packages.Count} packages, {assets.Count} bake payloads");
} catch(Exception error) {
    var cause=error;
    while(cause is TargetInvocationException && cause.InnerException is not null) cause=cause.InnerException;
    if(cause is IOException && ((cause.HResult & 0xffff)==112 || (cause.HResult & 0xffff)==39)) {
        Console.Error.WriteLine("[ATLASMAP_DISK_FULL] 磁盘空间不足，导出文件无法保存。"+cause.Message);
        Environment.ExitCode=112;
    } else if(cause is OutOfMemoryException || (cause.HResult & 0xffff) is 8 or 14 or 1450 or 1455) {
        Console.Error.WriteLine("[ATLASMAP_MEMORY_FULL] 内存或系统提交资源不足，当前分块需要降低并发后重试。"+cause);
        Environment.ExitCode=1455;
    } else {
        Console.Error.WriteLine(cause.ToString());Environment.ExitCode=1;
    }
} finally { if (provider is IDisposable disposable) disposable.Dispose(); }

internal static class NativeLinks {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool CreateHardLink(string newFile,string existingFile,IntPtr securityAttributes);
}
