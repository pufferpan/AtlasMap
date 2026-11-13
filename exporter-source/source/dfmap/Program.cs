using System.Diagnostics;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Objects.Core.Misc;
using Newtonsoft.Json;

namespace Dfmap;

public static class Program
{
    private static GameConfig _cfg;
    private static AesKeySet _keys;
    private static ConfigLoadResult _configuration;

    public static int Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        try
        {
            DeltaForceTypes.Register();
            if (Environment.GetEnvironmentVariable("ATLASMAP_TRACE_MESH") == "1") TracingStaticMesh.Register();
            if (Environment.GetEnvironmentVariable("ATLASMAP_TRACE") == "1") StreamedMesh.Verbose = true;
            return Run(args);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[atlas] FATAL {ex.GetType().Name}: {ex.Message}");
            if (Environment.GetEnvironmentVariable("ATLASMAP_TRACE") == "1") Console.Error.WriteLine(ex);
            return 1;
        }
    }

    private static int Run(string[] args)
    {
        var parsed = ConfigService.ExtractConfigArgument(args);
        args = parsed.Arguments;
        if (parsed.ConfigPath is not null) UseConfigFile(parsed.ConfigPath);
        EnsureConfig();

        var cmd = args.Length > 0 ? args[0].ToLowerInvariant() : "help";
        var rest = args.Skip(1).ToArray();

        // Diagnostics must be usable even when codecs or the game are absent.
        // In particular, this path never invokes decoder auto-download helpers.
        if (cmd == "doctor") return Doctor.Run(_configuration, rest);
        if (cmd is not ("help" or "--help" or "-h" or "api")) InitDecoders();

        switch (cmd)
        {
            case "keys": return CmdKeys();
            case "paks": return CmdPaks();
            case "probe": return CmdProbe(rest);
            case "umap": return CmdUmap(rest);
            case "find": return CmdFind(rest);
            case "maps": return CmdMaps(rest);
            case "api": return Inspect.CmdApi(rest);
            case "dump": return CmdDump(rest);
            case "tex": return CmdTex(rest);
            case "level": return CmdLevel(rest);
            case "scan": return CmdScan(rest);
            case "merge": return CmdMerge(rest);
            case "mesh": return CmdMesh(rest);
            case "raw": return CmdRaw(rest);
            case "lodtest": return CmdLodTest(rest);
            case "map": return CmdMap(rest);
            case "opts": return CmdOpts();
            case "dirs": return CmdDirs(rest);
            default:
                Console.WriteLine("""
                    dfmap - Game (该游戏) map export tool

                    usage: dfmap [--config path/to/dfmap.json] <command> [options]

                      keys                 show the AES key set that will be used
                      paks                 mount every pak and report what was loaded (M0)
                      find <substr> [n]    list virtual paths containing <substr> (default 50)
                      dump <pkg> [out]      serialize every export of a package to JSON
                      level <umap> [out]    one level: actors, mesh instances, LevelBounds cell
                      mesh <objPath>        diagnose one static mesh (properties, bCooked, RenderData)
                      raw <vpath> [out]     write a virtual file's raw bytes
                      scan <prefix> [out]   inventory a map family and infer the world grid
                      merge <map> <outDir>  merge a map into scene.glb + scene.json + reports
                      doctor [--mount] [--out report.json]
                                           check configuration and local dependencies; offline by default

                    config: --config > ATLASMAP_CONFIG > executable dfmap.json > working-directory dfmap.json > defaults
                    Windows JSON paths: use E:/Games or escaped backslashes; the GUI can save valid JSON.
                    """);
                return 0;
        }
    }

    /// <summary>
    /// Texture decoding needs three native helpers that CUE4Parse ships as managed wrappers
    /// only: Detex (BCn blocks), zlib-ng and Oodle. Without them every BC/DXT texture fails
    /// with "Detex decompression failed: not initialized". LoadDll/Initialize will fetch them
    /// on first use when they are not already present.
    /// </summary>
    private static void InitDecoders()
    {
        if (Environment.GetEnvironmentVariable("ATLASMAP_NO_DECODERS") == "1") return;
        var trace = Environment.GetEnvironmentVariable("ATLASMAP_TRACE") == "1";

        // LoadDll() reports success yet leaves the decoder uninitialised, which later surfaces as
        // "Detex decompression failed: not initialized" for every BC texture. Native libraries are
        // resolved against the app directory rather than the working directory, so the DLLs that
        // LoadDll drops next to the project are staged there and Initialized explicitly.
        var appDir = AppContext.BaseDirectory;
        var workDir = Directory.GetCurrentDirectory();
        var staged = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var name in new[] { "Detex.dll", "zlib-ng2.dll", "oodle-data-shared.dll" })
        {
            var dst = Path.Combine(appDir, name);
            try
            {
                if (!File.Exists(dst))
                {
                    var src = Path.Combine(workDir, name);
                    if (File.Exists(src)) File.Copy(src, dst, true);
                }
                if (File.Exists(dst)) staged[name] = dst;
            }
            catch (Exception ex) { if (trace) Console.Error.WriteLine($"[atlas] stage {name}: {ex.Message}"); }
        }

        try
        {
            var path = staged.GetValueOrDefault("Detex.dll");
            var ok = CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(path);
            if (path is not null) CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(path);
            if (trace) Console.Error.WriteLine($"[atlas] detex load={ok} path={path}");
        }
        catch (Exception ex) { if (trace) Console.Error.WriteLine($"[atlas] detex: {ex.GetType().Name}: {ex.Message}"); }
        try
        {
            var path = staged.GetValueOrDefault("oodle-data-shared.dll");
            if (path is not null) CUE4Parse.Compression.OodleHelper.Initialize(path);
            else CUE4Parse.Compression.OodleHelper.Initialize();
        }
        catch (Exception ex) { if (trace) Console.Error.WriteLine($"[atlas] oodle: {ex.GetType().Name}: {ex.Message}"); }
        try
        {
            var path = staged.GetValueOrDefault("zlib-ng2.dll");
            if (path is not null) CUE4Parse.Compression.ZlibHelper.Initialize(path);
            else CUE4Parse.Compression.ZlibHelper.Initialize();
        }
        catch (Exception ex) { if (trace) Console.Error.WriteLine($"[atlas] zlib: {ex.GetType().Name}: {ex.Message}"); }
    }

    private static AesKeySet Keys()
    {
        if (_keys is not null) return _keys;
        if (!File.Exists(_cfg.KeyFile))
        {
            // 未加密的游戏不需要密钥；加密的包会在 probe 里单独报出来，由 GUI 逐个询问。
            Console.Error.WriteLine($"[atlas] no key file at '{_cfg.KeyFile}'; only unencrypted archives can mount");
            _keys = new AesKeySet { Version = "none", MainKey = "" };
            return _keys;
        }
        _keys = AesKeySet.Load(_cfg.KeyFile);
        return _keys;
    }

    /// <summary>
    /// 报出每个归档是否需要密钥。已挂载 = 密钥正确；UnloadedVfs 里 IsEncrypted 的 = 还需要密钥
    /// （GUID 全零表示用主密钥）。JSON 输出给 GUI 逐个询问。
    /// </summary>
    private static int CmdProbe(string[] args)
    {
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        var archives = new List<object>();
        foreach (var v in provider.MountedVfs)
            archives.Add(new { file = Path.GetFileName(v.Name), encrypted = v.IsEncrypted,
                               guid = v.EncryptionKeyGuid.ToString(), mounted = true });
        foreach (var v in provider.UnloadedVfs)
            archives.Add(new { file = Path.GetFileName(v.Name), encrypted = v.IsEncrypted,
                               guid = v.EncryptionKeyGuid.ToString(), mounted = false });
        var result = new
        {
            game = _cfg.Game,
            paksDirectory = _cfg.PaksDirectory,
            mounted = provider.MountedVfs.Count,
            files = provider.Files.Count,
            archives,
        };
        var json = JsonConvert.SerializeObject(result, Formatting.Indented);
        if (args.Length > 0) File.WriteAllText(args[0], json);
        Console.WriteLine(json);
        return provider.Files.Count > 0 ? 0 : 3;
    }

    /// <summary>
    /// 导出任意游戏的一张 .umap，产物与 merge 相同（split/*.glb + manifest.json），
    /// 后面的 Blender 导入链不需要改。
    /// </summary>
    private static int CmdUmap(string[] args)
    {
        if (args.Length < 2) { Console.Error.WriteLine("usage: dfmap umap <vpath/Map.umap> <outDir>"); return 2; }
        var vpath = args[0].Replace('\\', '/');
        var outDir = args[1];
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        if (!provider.Files.Keys.Any(p => string.Equals(p, vpath, StringComparison.OrdinalIgnoreCase)))
        {
            Console.Error.WriteLine($"[dfmap] no such map: {vpath}");
            return 4;
        }
        var map = Path.GetFileNameWithoutExtension(vpath);
        Console.WriteLine($"[dfmap] exporting single map {vpath} -> {outDir}");
        return Merge.CmdMerge(provider, new[] { map, outDir, "--root", vpath, "--all", "--split" });
    }

    private static int CmdKeys()
    {
        var k = Keys();
        Console.WriteLine($"key file : {_cfg.KeyFile}");
        Console.WriteLine($"version  : {k.Version}");
        Console.WriteLine($"main key : {k.MainKey}");
        Console.WriteLine($"dynamic  : {k.Keys.Count} GUID-scoped keys");
        Console.WriteLine();
        Console.WriteLine("first 5:");
        foreach (var e in k.Keys.Take(5)) Console.WriteLine($"  {e.Guid}  {e.Key}");
        return 0;
    }

    private static int CmdPaks()
    {
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);

        Console.WriteLine();
        Console.WriteLine($"== mount summary ==");
        Console.WriteLine($"paks dir        : {_cfg.PaksDirectory}");
        Console.WriteLine($"key set         : {k.Version} (main + {k.Keys.Count})");
        Console.WriteLine($"archives mounted: {provider.MountedVfs.Count}");
        Console.WriteLine($"virtual files   : {provider.Files.Count}");

        var byExt = provider.Files.Values
            .GroupBy(f => f.Extension)
            .OrderByDescending(g => g.Count())
            .Take(20);
        Console.WriteLine();
        Console.WriteLine("== files by extension ==");
        foreach (var g in byExt) Console.WriteLine($"  {g.Key,-12} {g.Count(),10}");

        Console.WriteLine();
        Console.WriteLine("== sample mount points ==");
        foreach (var v in provider.MountedVfs.Take(8))
            Console.WriteLine($"  enc={v.IsEncrypted,-5} guid={v.EncryptionKeyGuid} mount={v.MountPoint}");

        return 0;
    }

    private static int CmdRaw(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap raw <virtualPath> [outFile]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        var path = args[0];
        if (!provider.TryGetGameFile(path, out var file))
        {
            // allow "Pkg/Object" style paths too
            var alt = path.Replace('\\', '/');
            if (!provider.TryGetGameFile(alt, out file))
            {
                Console.Error.WriteLine($"no such file: {path}");
                return 1;
            }
        }
        var data = file.Read();
        var outFile = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(), file.Name);
        File.WriteAllBytes(outFile, data);
        Console.WriteLine($"read : {file.Path}  (compressed={file.CompressionMethod}, encrypted={file.IsEncrypted})");
        Console.WriteLine($"size : {data.Length:n0} bytes  -> {outFile}");
        return 0;
    }

    private static int CmdOpts()
    {
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        var v = provider.Versions;
        Console.WriteLine($"game : {v.Game}");
        Console.WriteLine($"ver  : {v.Ver}");
        Console.WriteLine($"opts : {v.Options.Count} entries");
        foreach (var kv in v.Options.OrderBy(x => x.Key))
            Console.WriteLine($"  {kv.Key,-58} = {kv.Value}");
        Console.WriteLine();
        foreach (var probe in new[]
                 {
                     "StaticMesh.UseNewCookedFormat", "StaticMesh.HasNavCollision",
                     "StaticMesh.HasLODsShareStaticLighting", "StaticMesh.HasRayTracingGeometry",
                 })
        {
            bool value;
            try { value = v[probe]; } catch (Exception ex) { Console.WriteLine($"  {probe,-46} -> THROWS {ex.GetType().Name}"); continue; }
            Console.WriteLine($"  {probe,-46} -> {value}");
        }
        return 0;
    }

    private static int CmdDirs(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap dirs <prefix> [depth] [minFiles]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return MapTools.CmdDirs(provider, args);
    }

    private static int CmdMap(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap map <mapName|all> <outDir> [--mip N] [--swap-rb] [--list]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return MapImage.CmdMap(provider, args);
    }

    private static int CmdLodTest(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap lodtest <meshObjectPath> [...]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return StreamedMesh.CmdLodTest(provider, args);
    }

    private static int CmdMesh(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap mesh <meshObjectPath>"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        var path = args[0];
        var (pkgPath, objName) = MeshCache.SplitObjectPath(path);
        Console.WriteLine($"package : {pkgPath}");
        Console.WriteLine($"object  : {objName}");

        var pkg = provider.LoadPackage(pkgPath);
        Console.WriteLine($"exports : {pkg.ExportMapLength}   canDeserialize={pkg.CanDeserialize}");
        var flags = pkg.Summary.PackageFlags;
        Console.WriteLine($"flags   : {flags}");
        foreach (var lazy in pkg.ExportsLazy)
        {
            UObject o;
            try { o = lazy.Value; } catch (Exception ex) { Console.WriteLine($"  <error> {ex.Message}"); continue; }
            if (o is null) continue;
            Console.WriteLine($"  export {o.Name}  ({o.ExportType})  props={(o.Properties?.Count ?? -1)}");
            if (o.Name == objName && o.Properties is not null)
                foreach (var p in o.Properties)
                    Console.WriteLine($"      prop {p.Name} : {p.PropertyType}");
        }

        if (provider.TryGetGameFile(pkgPath + ".uasset", out var gf))
        {
            CUE4Parse.FileProvider.Objects.GameFile uexp;
            IReadOnlyList<CUE4Parse.FileProvider.Objects.GameFile> ubulks, uptnls;
            try
            {
                provider.Files.FindPayloads(gf, out uexp, out ubulks, out uptnls, false);
                Console.WriteLine($"\npayloads: uexp={uexp?.Path ?? "-"}  ubulk={ubulks?.Count ?? 0}  uptnl={uptnls?.Count ?? 0}");
                if (ubulks is not null)
                    foreach (var b in ubulks) Console.WriteLine($"    ubulk {b.Size,12:n0}  {b.Path}");
            }
            catch (Exception ex) { Console.WriteLine($"payload lookup failed: {ex.Message}"); }
        }

        var mesh = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh>(pkgPath, objName);
        if (mesh is not null)
        {
            Console.WriteLine($"\nUStaticMesh fields:");
            Console.WriteLine($"  bCooked        : {mesh.bCooked}");
            Console.WriteLine($"  HasTangents    : {mesh.HasTangents}");
            Console.WriteLine($"  RenderData     : {(mesh.RenderData is null ? "NULL" : $"LODs={mesh.RenderData.LODs?.Length}")}");
            Console.WriteLine($"  StaticMaterials: {mesh.StaticMaterials?.Length}");
            Console.WriteLine($"  Sockets        : {(mesh.Sockets is null ? "null" : mesh.Sockets.Length.ToString())}");
            Console.WriteLine($"  Materials      : {mesh.Materials?.Length}");
            Console.WriteLine($"  LODForCollision: {mesh.LODForCollision}");
        }

        var cache = new MeshCache(provider);
        var md = cache.Get(path);
        Console.WriteLine($"\nmesh: {(md is null ? "NOT DECODED" : $"{md.VertexCount} verts / {md.TriangleCount} tris  bounds=({md.BoundsMin[0]:0},{md.BoundsMin[1]:0},{md.BoundsMin[2]:0})..({md.BoundsMax[0]:0},{md.BoundsMax[1]:0},{md.BoundsMax[2]:0})")}");
        foreach (var r in cache.SkipReasons) Console.WriteLine($"  reason x{r.Value}: {r.Key}");
        foreach (var f in cache.Failures.Take(5)) Console.WriteLine($"  failure: {f}");
        return 0;
    }

    private static int CmdMerge(string[] args)
    {
        if (args.Length < 2) { Console.Error.WriteLine("usage: dfmap merge <mapRoot> <outDir> [--all] [--stats] [--root <prefix>]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return Merge.CmdMerge(provider, args);
    }

    private static int CmdScan(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap scan <pathPrefix> [outJson] [maxLevels]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return MapTools.CmdScan(provider, args);
    }

    private static int CmdLevel(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap level <umapPath> [outJson]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return Levels.CmdLevel(provider, args);
    }

    private static int CmdDump(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap dump <packagePath> [outFile]"); return 2; }
        var path = args[0];
        var outFile = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(),
            Path.GetFileNameWithoutExtension(path) + ".json");

        var k = Keys();
        using var provider = Mount.Create(_cfg, k);
        return Inspect.CmdDump(provider, path, outFile);
    }

    // ------------------------------------------------------------------------------------
    // Embedding facade: everything below exists so the WinForms front end (dfmap-gui) can
    // drive the same code paths as the CLI without shelling out to a second process.
    // ------------------------------------------------------------------------------------

    /// <summary>Set by the GUI to abort a long command between stages.</summary>
    public static volatile bool CancelRequested;

    /// <summary>Run a command exactly as the CLI would, capturing nothing and throwing nothing.</summary>
    public static int Execute(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        try
        {
            DeltaForceTypes.Register();
            return Run(args);
        }
        catch (OperationCanceledException)
        {
            Console.Error.WriteLine("[atlas] cancelled");
            return 130;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[atlas] FATAL {ex.GetType().Name}: {ex.Message}");
            if (Environment.GetEnvironmentVariable("ATLASMAP_TRACE") == "1") Console.Error.WriteLine(ex);
            return 1;
        }
    }

    private static void EnsureConfig()
    {
        if (_cfg is not null) return;
        ApplyConfiguration(ConfigService.Load(), resetSharedProvider: false);
    }

    public static ConfigLoadResult CurrentConfiguration()
    {
        EnsureConfig();
        // Callers receive a copy, so UI edits cannot silently mutate a mounted provider's config.
        return new ConfigLoadResult { Config = ConfigService.Normalize(_cfg), SourcePath = _configuration.SourcePath,
            Selection = _configuration.Selection, Warnings = new List<string>(_configuration.Warnings) };
    }

    public static void UseConfigFile(string path, bool resetSharedProvider = false) =>
        ApplyConfiguration(ConfigService.Load(path), resetSharedProvider);

    public static void Configure(GameConfig config, string sourcePath = null, bool resetSharedProvider = false) =>
        ApplyConfiguration(new ConfigLoadResult { Config = ConfigService.Normalize(config,
            sourcePath is null ? null : Path.GetDirectoryName(Path.GetFullPath(ConfigService.NormalizePath(sourcePath)))),
            SourcePath = sourcePath is null ? null : Path.GetFullPath(ConfigService.NormalizePath(sourcePath)), Selection = "GUI / embedding API" }, resetSharedProvider);

    private static void ApplyConfiguration(ConfigLoadResult loaded, bool resetSharedProvider)
    {
        var changed = _cfg is not null && ConfigService.Fingerprint(_cfg) != ConfigService.Fingerprint(loaded.Config);
        if (changed && _sharedProvider is not null && !resetSharedProvider)
            throw new InvalidOperationException("The game provider is already mounted with another configuration. Finish the active operation and explicitly reset/re-mount before changing game version or keys.");
        if (resetSharedProvider || changed)
        {
            _sharedProvider?.Dispose();
            _sharedProvider = null;
            _keys = null;
        }
        _configuration = loaded;
        _cfg = loaded.Config;
        Console.Error.WriteLine($"[atlas] config: {loaded.SourcePath ?? "(built-in defaults)"} ({loaded.Selection})");
        foreach (var warning in loaded.Warnings) Console.Error.WriteLine("[atlas] config warning: " + warning);
    }

    private static IFileProvider _sharedProvider;

    /// <summary>
    /// A mounted provider that outlives a single command. Mounting 292 archives costs a couple
    /// of seconds, which is fine once per CLI run but not once per GUI interaction.
    /// </summary>
    public static IFileProvider SharedProvider()
    {
        EnsureConfig();
        InitDecoders();
        return _sharedProvider ??= Mount.Create(_cfg, Keys());
    }

    /// <summary>Every folder under Content/Maps, i.e. the maps this build ships.</summary>
    public static List<string> ListMaps()
    {
        const string prefix = "DeltaForce/Content/Maps/";
        var set = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var f in SharedProvider().Files.Keys)
        {
            if (!f.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
            var rest = f[prefix.Length..];
            var slash = rest.IndexOf('/');
            if (slash > 0) set.Add(rest[..slash]);
        }
        return set.ToList();
    }

    /// <summary>
    /// The roots a map's content is spread over. Most maps keep their geometry in
    /// Content/Maps/&lt;map&gt;, but the "built" HD tiles live in a sibling tree and a map is
    /// incomplete without them.
    /// </summary>
    public static List<string> SuggestRoots(string map)
    {
        var provider = SharedProvider();
        var roots = new List<string>();
        foreach (var prefix in new[] { "DeltaForce/Content/Maps/", "DeltaForce/Content/Maps/BuildMaps_HD/" })
        {
            var candidate = $"{prefix}{map}/";
            if (provider.Files.Keys.Any(k => k.StartsWith(candidate, StringComparison.OrdinalIgnoreCase)))
                roots.Add(candidate);
        }
        if (roots.Count == 0) roots.Add($"DeltaForce/Content/Maps/{map}/");
        return roots;
    }

    /// <summary>List the maps this build ships (one folder per map under Content/Maps).</summary>
    private static int CmdMaps(string[] args)
    {
        var maps = ListMaps();
        if (args.Length > 0)
        {
            foreach (var r in SuggestRoots(args[0])) Console.WriteLine(r);
            return 0;
        }
        Console.WriteLine($"\n== {maps.Count} maps under Content/Maps ==");
        foreach (var m in maps) Console.WriteLine("  " + m);
        Console.WriteLine("\nusage: dfmap maps <map>   ->  print the --root list for one map");
        return 0;
    }

    private static int CmdFind(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap find <substr> [limit]"); return 2; }
        var needle = args[0];
        var limit = args.Length > 1 ? int.Parse(args[1]) : 50;

        var k = Keys();
        using var provider = Mount.Create(_cfg, k);

        var hits = provider.Files.Values
            .Where(f => f.Path.Contains(needle, StringComparison.OrdinalIgnoreCase))
            .OrderBy(f => f.Path, StringComparer.OrdinalIgnoreCase)
            .ToList();

        Console.WriteLine();
        Console.WriteLine($"== {hits.Count} files matching \"{needle}\" (showing {Math.Min(limit, hits.Count)}) ==");
        foreach (var h in hits.Take(limit))
            Console.WriteLine($"  {h.Size,12:n0}  {h.Path}");
        return 0;
    }

    /// <summary>
    /// Decode a single UTexture2D (or every sibling variant of it) to a PNG and report what
    /// happened, so texture-yield work does not need a full scene merge per iteration.
    /// </summary>
    private static int CmdTex(string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap tex <texturePath> [outDir]"); return 2; }
        var k = Keys();
        using var provider = Mount.Create(_cfg, k);

        var outDir = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(), "map_tex");
        var cache = new TextureCache(provider, outDir);
        foreach (var path in args[0].Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var file = cache.Texture(path);
            Console.WriteLine(file is null
                ? $"FAIL  {path}"
                : $"OK    {path}  -> {file.RelativePath}  {file.Width}x{file.Height}  {file.Bytes:n0} B");
        }
        Console.WriteLine($"\ndecoded {cache.DecodedCount}, undecodable {cache.Missed}, " +
                          $"variant fallbacks {cache.Fallbacks}, out {outDir}");
        foreach (var f in cache.Failures.Take(12)) Console.WriteLine("  ! " + f);
        return 0;
    }
}
