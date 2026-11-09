using System.Text;
using System.Text.RegularExpressions;
using CUE4Parse.FileProvider;
using Newtonsoft.Json;

namespace Dfmap;

public sealed class LevelDecision
{
    public string Level { get; set; }
    public bool Include { get; set; }
    public string Reason { get; set; }
    public int Actors { get; set; }
    public int Instances { get; set; }
}

public sealed class MergeReport
{
    public string MapRoot { get; set; }
    public string Policy { get; set; }
    public int LevelsFound { get; set; }
    public int LevelsIncluded { get; set; }
    public int Instances { get; set; }
    public int UniqueMeshes { get; set; }
    public int DecodedMeshes { get; set; }
    public long Vertices { get; set; }
    public long Triangles { get; set; }
    public double GlbMB { get; set; }
    public float[] WorldBoundsMinUE { get; set; }
    public float[] WorldBoundsMaxUE { get; set; }
    public float[] WorldBoundsMinGltf { get; set; }
    public float[] WorldBoundsMaxGltf { get; set; }
    public List<LevelDecision> Levels { get; set; } = new();
    public List<string> Warnings { get; set; } = new();
}

public static class Merge
{
    // Levels that are auxiliary renders/bakes of a building rather than new geometry.
    private static readonly Regex Helper = new(
        @"(_In_)?(Lighting(_Data)?(_HD)?|SQ(_HD)?|SSQ(_HD)?|Reflection(_HD)?|Reflection_Mobile|DecalActor_HD|Mobile)$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex Alternate = new(
        @"_Without(HighValue|Event|.*)$", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public static int CmdMerge(IFileProvider provider, string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("usage: dfmap merge <mapRoot> <outDir> [--all] [--stats] [--root <prefix>] [--mesh-game <EGame>]");
            Console.Error.WriteLine("  e.g. dfmap merge AZ-5 G:\\out");
            return 2;
        }
        var map = args[0];
        var outDir = args[1];
        var policy = args.Contains("--all") ? "all" : "default";
        var statsOnly = args.Contains("--stats");
        var plan = args.Contains("--plan");
        var uemodel = args.Contains("--uemodel");
        var explicitRoot = GetOpt(args, "--root");
        var meshGame = GetOpt(args, "--mesh-game") ?? Environment.GetEnvironmentVariable("ATLASMAP_MESH_GAME");
        var excludes = (GetOpt(args, "--exclude") ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        // --bbox x0,y0,x1,y1 (UE cm): keep only levels whose LevelBounds centre falls inside.
        // Map folders often mix the actual map with far-away open-world quest/event variants.
        float[] bbox = null;
        if (GetOpt(args, "--bbox") is { } bboxArg)
        {
            var parts = bboxArg.Split(',').Select(float.Parse).ToArray();
            if (parts.Length != 4) { Console.Error.WriteLine("--bbox needs x0,y0,x1,y1"); return 2; }
            bbox = parts;
        }

        // --root accepts a comma-separated list so a map whose content is spread over several
        // trees (e.g. SafeHouse = SafeHouse + BuildMaps_HD/SafeHouse + Iris/.../SafeHouse) can be
        // merged in one pass.
        var mapRoots = (explicitRoot ?? $"DeltaForce/Content/Maps/{map}/")
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToList();
        var mapRoot = string.Join(" + ", mapRoots);
        Directory.CreateDirectory(outDir);

        // ---------------- 1. enumerate + select ----------------
        var all = provider.Files.Keys
            .Where(p => p.EndsWith(".umap", StringComparison.OrdinalIgnoreCase)
                        && mapRoots.Any(r => p.StartsWith(r, StringComparison.OrdinalIgnoreCase)))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(p => p, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var decisions = new List<LevelDecision>();
        var byName = all.ToDictionary(p => p, p => Path.GetFileNameWithoutExtension(p), StringComparer.OrdinalIgnoreCase);
        var hdPresent = all.Select(p => byName[p])
                           .Where(n => n.EndsWith("_HD", StringComparison.OrdinalIgnoreCase))
                           .Select(n => n[..^3])
                           .ToHashSet(StringComparer.OrdinalIgnoreCase);

        foreach (var p in all)
        {
            var name = byName[p];
            string reason = "kept";
            var include = true;
            if (policy != "all")
            {
                if (Alternate.IsMatch(name)) { include = false; reason = "alternate gameplay variant (_Without*)"; }
                else if (Helper.IsMatch(name)) { include = false; reason = "auxiliary bake/render level"; }
                else if (name.EndsWith("_HD", StringComparison.OrdinalIgnoreCase)
                         && Helper.IsMatch(name[..^3])) { include = false; reason = "auxiliary bake/render level (_HD)"; }
                else if (hdPresent.Contains(name) && !args.Contains("--keep-base-with-hd")) { include = false; reason = "superseded by its _HD sibling"; }
            }
            if (include && excludes.Length > 0)
            {
                var hit = excludes.FirstOrDefault(e => p.Contains(e, StringComparison.OrdinalIgnoreCase));
                if (hit is not null) { include = false; reason = $"excluded by --exclude '{hit}'"; }
            }
            decisions.Add(new LevelDecision { Level = p, Include = include, Reason = reason });
        }

        var selected = decisions.Where(d => d.Include).Select(d => d.Level).ToList();
        Console.WriteLine($"map root      : {mapRoot}");
        Console.WriteLine($"levels found  : {all.Count}");
        Console.WriteLine($"levels kept   : {selected.Count}   (policy: {policy})");

        // ---------------- 2. extract instances ----------------
        var report = new MergeReport { MapRoot = mapRoot, Policy = policy, LevelsFound = all.Count };
        var instances = new List<(string Mesh, float[] Loc, float[] Rot, float[] Scale, float[] Extent, string Name, float[] MatrixUE, SourceInstanceMetadata Source)>();
        var lights = new List<LightInstance>();
        var sw = System.Diagnostics.Stopwatch.StartNew();

        for (var i = 0; i < selected.Count; i++)
        {
            var p = selected[i];
            var d = decisions.First(x => x.Level == p);
            try
            {
                var s = Levels.Extract(provider, p, includeHidden: !args.Contains("--visible-only"));
                d.Actors = s.ActorCount;
                d.Instances = s.InstanceCount;
                if (bbox is not null)
                {
                    var c = s.BoundsCenter;
                    var inside = c is not null
                                 && c[0] >= bbox[0] && c[0] <= bbox[2]
                                 && c[1] >= bbox[1] && c[1] <= bbox[3];
                    if (!inside)
                    {
                        d.Include = false;
                        d.Reason = c is null
                            ? "no LevelBounds, dropped by --bbox"
                            : $"outside --bbox (centre {c[0]:0},{c[1]:0})";
                        if (s.Errors.Count > 0) report.Warnings.Add($"{p}: {s.Errors.Count} extraction errors");
                        continue;
                    }
                }
                foreach (var inst in s.Instances)
                    instances.Add((inst.Mesh, inst.Loc, inst.Rot, inst.Scale, inst.Extent,
                                   $"{Path.GetFileNameWithoutExtension(p)}/{inst.Actor}/{inst.Component}" + (inst.Source?.SourceInstanceIndex is {} ii ? $"[{ii}]" : ""), inst.MatrixUE, inst.Source));
                lights.AddRange(s.Lights);
                if (s.Errors.Count > 0) report.Warnings.Add($"{p}: {s.Errors.Count} extraction errors");
            }
            catch (Exception ex)
            {
                report.Warnings.Add($"{p}: {ex.GetType().Name}: {ex.Message}");
            }
            if (Program.CancelRequested) throw new OperationCanceledException("export cancelled");
            if ((i + 1) % 25 == 0 || i + 1 == selected.Count)
                Console.WriteLine($"  extracted {i + 1,4}/{selected.Count} levels, {instances.Count,7} instances ({sw.Elapsed.TotalSeconds:0}s)");
        }

        if(GetOpt(args,"--mesh-exclude") is {} meshExclusions)
        {
            var tokens=meshExclusions.Split(',',StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
            instances=instances.Where(x=>!tokens.Any(token=>x.Mesh.Contains(token,StringComparison.OrdinalIgnoreCase))).ToList();
        }
        if (GetOpt(args,"--mesh-filter") is { } meshFilter)
        {
            var countBefore=instances.Count;
            instances=instances.Where(x=>x.Mesh.Contains(meshFilter,StringComparison.OrdinalIgnoreCase)).ToList();
            Console.WriteLine($"--mesh-filter kept {instances.Count}/{countBefore} placements matching '{meshFilter}'");
        }
        if (GetOpt(args,"--instance-bbox") is { } instanceBox)
        {
            var box = instanceBox.Split(',').Select(float.Parse).ToArray();
            if (box.Length != 4) throw new ArgumentException("--instance-bbox needs x0,y0,x1,y1");
            var countBefore = instances.Count;
            instances = instances.Where(x => x.Loc[0]>=box[0] && x.Loc[0]<=box[2] && x.Loc[1]>=box[1] && x.Loc[1]<=box[3]).ToList();
            Console.WriteLine($"removed {countBefore-instances.Count} placements outside --instance-bbox");
        }
        if (args.Contains("--deduplicate"))
        {
            var seenInstances = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var beforeCount = instances.Count;
            instances = instances.Where(x => seenInstances.Add(x.Mesh + "|" + x.Source?.AppearanceSignature() + "|" + string.Join(",",
                (x.MatrixUE ?? GlbWriter.BuildNodeMatrix(x.Loc,x.Rot,x.Scale))
                    .Select((v,i) => Math.Round(v, i>=12 && i<15 ? 1 : 5).ToString("R",System.Globalization.CultureInfo.InvariantCulture))))).ToList();
            Console.WriteLine($"deduplicated {beforeCount - instances.Count} repeated placements");
        }
        report.LevelsIncluded = decisions.Count(d=>d.Include);
        report.Levels = decisions;
        report.Instances = instances.Count;

        // ---------------- 3. decode unique meshes ----------------
        var meshPaths = instances.Select(x => x.Mesh).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        report.UniqueMeshes = meshPaths.Count;
        Console.WriteLine($"\nunique meshes : {meshPaths.Count}  -> decoding LOD0");

        var cache = new MeshCache(provider, meshGame);
        var writer = new GlbWriter();
        var decoded = 0;
        long verts = 0, tris = 0;
        foreach (var mp in meshPaths)
        {
            if (Program.CancelRequested) throw new OperationCanceledException("export cancelled");
            var md = cache.Get(mp);
            if (md is null) continue;
            decoded++;
            verts += md.VertexCount;
            tris += md.TriangleCount;
            if (decoded % 100 == 0)
                Console.WriteLine($"  decoded {decoded,5}/{meshPaths.Count} meshes, {verts,9} verts, {tris,9} tris ({sw.Elapsed.TotalSeconds:0}s)");
        }
        report.DecodedMeshes = decoded;
        report.Vertices = verts;
        report.Triangles = tris;
        report.Warnings.AddRange(cache.Failures.Take(40).Select(f => "mesh decode failed: " + f));
        Console.WriteLine($"  decoded {decoded}/{meshPaths.Count} meshes, {verts} verts, {tris} tris ({sw.Elapsed.TotalSeconds:0}s)");
        if (cache.SkipReasons.Count > 0)
        {
            Console.WriteLine("  skipped meshes by reason:");
            foreach (var kv in cache.SkipReasons.OrderByDescending(k => k.Value))
                Console.WriteLine($"    {kv.Value,5}  {kv.Key}");
            report.Warnings.AddRange(cache.SkipReasons.Select(kv => $"mesh skipped x{kv.Value}: {kv.Key}"));
            if (cache.BoundsRejected > 0)
            {
                Console.WriteLine($"  rejected by declared ExtendedBounds: {cache.BoundsRejected}");
                report.Warnings.Add($"CUE4Parse decodes rejected for falling outside the asset's " +
                                    $"declared ExtendedBounds: {cache.BoundsRejected}");
            }
            var skipTxt = new List<string> { "# skipped meshes", "" };
            skipTxt.AddRange(cache.SkippedPaths);
            File.WriteAllText(Path.Combine(outDir, "skipped_meshes.md"), string.Join(Environment.NewLine, skipTxt));
            Console.WriteLine($"  skipped list -> {Path.Combine(outDir, "skipped_meshes.md")} ({cache.SkippedPaths.Count})");
        }

        // ---------------- 4. place instances ----------------
        var minUE = new[] { float.MaxValue, float.MaxValue, float.MaxValue };
        var maxUE = new[] { float.MinValue, float.MinValue, float.MinValue };
        var minG = new[] { float.MaxValue, float.MaxValue, float.MaxValue };
        var maxG = new[] { float.MinValue, float.MinValue, float.MinValue };
        var placed = 0;
        var planItems = new List<PlanView.Item>();
        var withExtent = 0;

        // geometry accumulated in world space for the .uemodel export (UEFormat has no instancing)
        var uePos = new List<float>();
        var ueNrm = new List<float>();
        var ueUv = new List<float>();
        var ueIdx = new List<uint>();
        var ueMats = new List<UeFormat.Material>();

        // --split: one world-space-baked file per source level. Everything is baked to absolute
        // coordinates and no node transform is written, so importing these removes instancing
        // from the equation entirely - if a single level is out of place, the file that is out of
        // place can be pointed at directly instead of bisecting the whole scene.
        var split = args.Contains("--split");
        var perLevel = split ? new Dictionary<string, List<(string Mesh, float[] Loc, float[] Rot, float[] Scale, float[] MatrixUE, SourceInstanceMetadata Source)>>(StringComparer.OrdinalIgnoreCase) : null;
        var perLevelOrder = split ? new List<string>() : null;

        foreach (var (mesh, loc, rot, scale, extent, name, matrixUE, source) in instances)
        {
            var md = MaterialBinding.Apply(cache.Get(mesh),source?.OverrideMaterials);
            if (md is null) continue;
            writer.AddInstance(writer.AddMesh(md), loc, rot, scale, name, matrixUE,source);
            placed++;

            if (perLevel is not null)
            {
                var lvl = source?.SourceLevel ?? (name.Contains('/') ? name[..name.IndexOf('/')] : name);
                if (!perLevel.TryGetValue(lvl, out var list))
                {
                    perLevel[lvl] = list = new List<(string, float[], float[], float[], float[], SourceInstanceMetadata)>();
                    perLevelOrder.Add(lvl);
                }
                list.Add((mesh, loc, rot, scale, matrixUE, source));
            }

            if (uemodel)
                AppendWorldGeometry(uePos, ueNrm, ueUv, ueIdx, ueMats, md, loc, rot, scale, name, matrixUE);

            // Transform all eight declared local AABB corners. Translation-only bounds
            // are wrong for rotated/negative-scale components and corrupt map reports.
            var (lo,hi)=InstanceBounds(md,loc,rot,scale,matrixUE);
            for(var a=0;a<3;a++)
            {minUE[a]=MathF.Min(minUE[a],lo[a]);maxUE[a]=MathF.Max(maxUE[a],hi[a]);}

            planItems.Add(new PlanView.Item
            {
                X = loc?[0] ?? 0f,
                Y = loc?[1] ?? 0f,
                Z = loc?[2] ?? 0f,
                FootprintX = MathF.Max(hi[0] - lo[0], 30f),
                FootprintY = MathF.Max(hi[1] - lo[1], 30f),
                BoundsKnown = true,
            });

            // Match the actual writer: UE(x,y,z) -> glTF(x,z,y)*.01.
            var gl = new[] { lo[0]/100f, lo[2]/100f, lo[1]/100f };
            var gh = new[] { hi[0]/100f, hi[2]/100f, hi[1]/100f };
            for (var a = 0; a < 3; a++)
            {
                if (gl[a] < minG[a]) minG[a] = gl[a];
                if (gh[a] > maxG[a]) maxG[a] = gh[a];
            }
        }
        report.WorldBoundsMinUE = placed > 0 ? minUE : null;
        report.WorldBoundsMaxUE = placed > 0 ? maxUE : null;
        report.WorldBoundsMinGltf = placed > 0 ? minG : null;
        report.WorldBoundsMaxGltf = placed > 0 ? maxG : null;
        if (placed == 0) report.Warnings.Add("No geometry remains after selection/filtering, or no selected mesh could be decoded. World bounds are absent.");
        Console.WriteLine($"\nplaced {placed} instances, {writer.MeshCount} meshes, {writer.NodeCount} nodes");
        report.Instances = placed;
        report.Warnings.Add("Static geometry/PBR export: original water simulation, full cooked shader math, " +
                            "custom GI/PRT and gameplay collision are not automatically reconstructed. " +
                            "Source visibility, overrides and serialized collision settings are retained in scene.json and GLB node extras.dfmap.");
        if(uemodel)report.Warnings.Add("UEFormat baked export cannot retain per-instance visibility/identity metadata; use GLB plus scene.json for source-aware reconstruction.");

        // ---------------- 5. write ----------------
        File.WriteAllText(Path.Combine(outDir, "selection.json"),
            JsonConvert.SerializeObject(decisions, Formatting.Indented));

        if (!statsOnly)
        {
            // ---- textures: resolve every material in use and decode its maps ----
            if (!args.Contains("--no-textures"))
            {
                var maxTex = GetOpt(args, "--max-tex") is { } mt ? int.Parse(mt) : 1024;
                var texCache = new TextureCache(provider, outDir, "textures", maxTex);
                var materialPaths = cache.DecodedMeshes
                    .SelectMany(m => m.Materials)
                    .Concat(instances.SelectMany(i => i.Source?.OverrideMaterials ?? new List<string>()))
                    .Where(s => !string.IsNullOrEmpty(s))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList();
                var sw2 = System.Diagnostics.Stopwatch.StartNew();
                var withTex = 0;
                foreach (var mp in materialPaths)
                {
                    if (Program.CancelRequested) throw new OperationCanceledException("export cancelled");
                    var info = texCache.Material(mp);
                    if (info is null) continue;
                    var bc = texCache.Texture(info.BaseColor);
                    var nrm = texCache.Texture(info.Normal);
                    var mra = texCache.Texture(info.Mra);
                    if (bc is null && nrm is null && mra is null) continue;
                    withTex++;
                    writer.MaterialTextureFiles[mp] = (bc?.RelativePath, nrm?.RelativePath, mra?.RelativePath, info.Tint);
                }
                Console.WriteLine($"\n[textures] {materialPaths.Count} materials, {withTex} with textures, " +
                                  $"{texCache.DecodedCount} PNGs decoded ({texCache.TotalBytes / 1048576.0:0.0} MB, " +
                                  $"max {maxTex}px) in {sw2.Elapsed.TotalSeconds:0}s");
                var missingMats = cache.DecodedMeshes.Count(m => m.Materials.Count == 0);
                Console.WriteLine($"[textures] meshes with no material slot: {missingMats}/{cache.DecodedMeshes.Count()}; " +
                                  $"variant fallbacks: {texCache.Fallbacks}; undecodable: {texCache.Missed}");
                if (texCache.MissReasons.Count > 0)
                {
                    Console.WriteLine("[textures] why textures were missed:");
                    foreach (var kv in texCache.MissReasons.OrderByDescending(k => k.Value).Take(8))
                        Console.WriteLine($"    {kv.Value,6}  {kv.Key}");
                    report.Warnings.Add("texture misses by reason: " + string.Join("; ",
                        texCache.MissReasons.OrderByDescending(k => k.Value).Take(6)
                            .Select(k => $"{k.Key} x{k.Value}")));
                }
                report.Warnings.Add($"texture yield: {withTex}/{materialPaths.Count} materials textured, " +
                                    $"{texCache.DecodedCount} PNGs, {texCache.Fallbacks} via platform-variant fallback, " +
                                    $"{texCache.Missed} textures undecodable, {missingMats} meshes with no material slot");
                if (texCache.Failures.Count > 0)
                    report.Warnings.AddRange(texCache.Failures.Take(20).Select(f => "texture: " + f));
            }

            var glb = Path.Combine(outDir, "scene.glb");
            writer.Lights = lights;
            // A monolithic scene.glb is assembled entirely in memory, so it runs out of address
            // space on the biggest maps - AZ-5 with its BuildMaps_HD tree is 32M vertices /
            // 47M triangles and died with OutOfMemoryException after every other stage had
            // succeeded. --no-scene skips it; --split still writes the per-level files, which are
            // far more usable at that size anyway (Blender will not enjoy a 70k-instance node
            // graph either).
            if (args.Contains("--no-scene"))
            {
                Console.WriteLine("[glb] skipped (--no-scene); use --split for per-level files");
                report.Warnings.Add("scene.glb skipped by --no-scene on account of scene size");
            }
            else
            {
                writer.Write(glb, map);
                report.GlbMB = Math.Round(new FileInfo(glb).Length / 1024.0 / 1024.0, 2);
                Console.WriteLine($"wrote {glb}  ({report.GlbMB} MB)");
            }

            var byType = lights.GroupBy(l => l.Type).OrderByDescending(g => g.Count()).ToList();
            Console.WriteLine($"[lights] {lights.Count}  " +
                              string.Join("  ", byType.Select(g => $"{g.Key}={g.Count()}")));
            if (writer.UnsupportedLights.Count > 0)
                Console.WriteLine($"[lights] not representable in glTF: " +
                                  string.Join(", ", writer.UnsupportedLights.Select(kv => $"{kv.Key}={kv.Value}")));
            File.WriteAllText(Path.Combine(outDir, "lights.json"),
                JsonConvert.SerializeObject(new
                {
                    note = "UE centimetres, Z-up, left-handed; roll/pitch/yaw in degrees. " +
                           "Scene.glb carries these through KHR_lights_punctual where glTF supports it.",
                    counts = byType.ToDictionary(g => g.Key, g => g.Count()),
                    unsupported = writer.UnsupportedLights,
                    lights,
                }, Formatting.Indented));
        }

        // scene index (instances only, no geometry) for downstream tooling
        var indexOut = Path.Combine(outDir, "scene.json");
        File.WriteAllText(indexOut, JsonConvert.SerializeObject(new
        {
            mapRoot,
            policy,
            schemaVersion = 2,
            coordinateSystem = "UE centimetres, Z-up; matrixUE column-major; Blender=UE(x,-y,z)*0.01",
            includesHidden = !args.Contains("--visible-only"),
            instances = instances.Select(x => new { mesh = x.Mesh, loc = x.Loc, rot = x.Rot, scale = x.Scale, name = x.Name, matrixUE = x.MatrixUE, dfmap = x.Source }),
        }, Formatting.Indented));
        Console.WriteLine($"wrote {indexOut}");

        File.WriteAllText(Path.Combine(outDir, "merge_report.json"),
            JsonConvert.SerializeObject(report, Formatting.Indented));
        WriteMarkdownReport(Path.Combine(outDir, "report.md"), report);
        Console.WriteLine($"wrote {Path.Combine(outDir, "report.md")}");

        if (plan)
        {
            // undecodable meshes get a marker; prefer the component's own world bounds when
            // the package serialized them, otherwise fall back to a fixed marker
            foreach (var (mesh, loc, rot, scale, extent, name, matrixUE, source) in instances)
            {
                if (cache.Get(mesh) is not null) continue;
                float fx, fy;
                var known = extent is not null && (extent[0] > 1f || extent[1] > 1f);
                if (known)
                {
                    fx = extent[0] * 2f; fy = extent[1] * 2f;
                    withExtent++;
                }
                else
                {
                    var s = MathF.Max(MathF.Abs(scale?[0] ?? 1f), 1f);
                    fx = fy = 150f * s;
                }
                planItems.Add(new PlanView.Item
                {
                    X = loc?[0] ?? 0f,
                    Y = loc?[1] ?? 0f,
                    Z = loc?[2] ?? 0f,
                    FootprintX = MathF.Max(fx, 40f),
                    FootprintY = MathF.Max(fy, 40f),
                    BoundsKnown = known,
                });
            }
            Console.WriteLine($"[plan] undecoded meshes with serialized component bounds: {withExtent}");
            PlanView.Render(Path.Combine(outDir, "plan.png"), planItems);
            File.WriteAllText(Path.Combine(outDir, "plan_items.json"),
                JsonConvert.SerializeObject(new
                {
                    note = "XY in UE centimetres; Z drives the colour ramp",
                    min = report.WorldBoundsMinUE,
                    max = report.WorldBoundsMaxUE,
                    count = planItems.Count,
                }, Formatting.Indented));
        }

        if (uemodel && ueIdx.Count > 0)
        {            // UEFormat has no per-instance nodes, so everything is baked into one mesh. Shift
            // the origin to the map centre to keep float32 precision usable on huge maps.
            var origin = new[]
            {
                MathF.Round((minUE[0] + maxUE[0]) / 2f),
                MathF.Round((minUE[1] + maxUE[1]) / 2f),
                MathF.Round((minUE[2] + maxUE[2]) / 2f),
            };
            for (var i = 0; i + 2 < uePos.Count; i += 3)
            {
                uePos[i] -= origin[0];
                uePos[i + 1] -= origin[1];
                uePos[i + 2] -= origin[2];
            }

            var uePath = Path.Combine(outDir, "scene.uemodel");
            UeFormat.Write(uePath, map, $"/Game/Maps/{map}", new[]
            {
                new UeFormat.Lod
                {
                    Name = "Map",
                    Positions = uePos.ToArray(),
                    Normals = ueNrm.ToArray(),
                    Uvs = ueUv.ToArray(),
                    Indices = ueIdx.ToArray(),
                    Materials = ueMats,
                },
            });
            File.WriteAllText(Path.Combine(outDir, "uemodel_origin.json"),
                JsonConvert.SerializeObject(new
                {
                    note = "vertex data is written in UE centimetres, Z-up, already offset by this origin; " +
                           "the UEFormat Blender addon scales by 0.01 and mirrors Y",
                    originCm = origin,
                    vertices = uePos.Count / 3,
                    triangles = ueIdx.Count / 3,
                    materials = ueMats.Count,
                }, Formatting.Indented));
            Console.WriteLine($"[uemodel] {uePos.Count / 3:n0} vertices / {ueIdx.Count / 3:n0} triangles, " +
                              $"{ueMats.Count} material slots -> {uePath} " +
                              $"({new FileInfo(uePath).Length / 1024.0 / 1024.0:0.0} MB)");
        }

        if (placed > 0)
        {
            Console.WriteLine($"\n== world bounds (UE cm) ==  min=({minUE[0]:0},{minUE[1]:0},{minUE[2]:0})  max=({maxUE[0]:0},{maxUE[1]:0},{maxUE[2]:0})");
            Console.WriteLine($"== size ==  {(maxUE[0] - minUE[0]) / 100:0} m x {(maxUE[1] - minUE[1]) / 100:0} m x {(maxUE[2] - minUE[2]) / 100:0} m");
        }
        else Console.WriteLine("No geometry remains after selection/filtering; world bounds are absent.");

        if (perLevel is not null)
        {
            _splitMaterials = writer.MaterialTextureFiles;
            WriteSplit(outDir, map, perLevel, perLevelOrder, cache, uemodel, steps: ueIdx.Count);
        }

        return 0;
    }

    /// <summary>
    /// UE placement maths in one place: local point -> scale -> rotate -> translate, in UE axes.
    /// Both the world-space bake and the manifest bounds go through this, so the two can never
    /// drift apart the way the axis map did when it was written out twice.
    /// </summary>
    private static (float X, float Y, float Z) TransformPoint(double[][] r, float[] s, float[] t,
                                                              float px, float py, float pz, float[] matrixUE = null)
    {
        if (matrixUE is not null)
            return (matrixUE[0]*px+matrixUE[4]*py+matrixUE[8]*pz+matrixUE[12],
                    matrixUE[1]*px+matrixUE[5]*py+matrixUE[9]*pz+matrixUE[13],
                    matrixUE[2]*px+matrixUE[6]*py+matrixUE[10]*pz+matrixUE[14]);
        var vx = px * s[0];
        var vy = py * s[1];
        var vz = pz * s[2];
        return ((float)(r[0][0] * vx + r[0][1] * vy + r[0][2] * vz + t[0]),
                (float)(r[1][0] * vx + r[1][1] * vy + r[1][2] * vz + t[1]),
                (float)(r[2][0] * vx + r[2][1] * vy + r[2][2] * vz + t[2]));
    }

    public static (float[] Min,float[] Max) InstanceBounds(MeshData mesh,float[] loc,float[] rot,float[] scale,float[] matrixUE=null)
    {
        var lo=new[]{float.MaxValue,float.MaxValue,float.MaxValue};
        var hi=new[]{float.MinValue,float.MinValue,float.MinValue};
        var r=UeFormat.RotationMatrix(rot?[0]??0,rot?[1]??0,rot?[2]??0);
        var s=scale??new[]{1f,1f,1f};var t=loc??new float[3];
        for(var corner=0;corner<8;corner++)
        {
            var p=TransformPoint(r,s,t,(corner&1)==0?mesh.BoundsMin[0]:mesh.BoundsMax[0],
                (corner&2)==0?mesh.BoundsMin[1]:mesh.BoundsMax[1],(corner&4)==0?mesh.BoundsMin[2]:mesh.BoundsMax[2],matrixUE);
            var values=new[]{p.X,p.Y,p.Z};
            for(var axis=0;axis<3;axis++){lo[axis]=MathF.Min(lo[axis],values[axis]);hi[axis]=MathF.Max(hi[axis],values[axis]);}
        }
        return(lo,hi);
    }

    /// <summary>
    /// Write one file per source level, with every vertex already transformed into absolute
    /// world coordinates and no node transform anywhere.
    ///
    /// This exists because the instanced scene is hard to debug: when one prop is in the wrong
    /// place you cannot tell whether the instance transform, the mesh's local geometry or the
    /// axis mapping is at fault. A per-level bake removes the first of those three, and a
    /// manifest records where each file is supposed to sit so a mismatch is obvious on sight.
    /// </summary>
    private static void WriteSplit(string outDir, string map,
                                   Dictionary<string, List<(string Mesh, float[] Loc, float[] Rot, float[] Scale, float[] MatrixUE, SourceInstanceMetadata Source)>> perLevel,
                                   List<string> order, MeshCache cache, bool uemodel, int steps)
    {
        var splitDir = Path.Combine(outDir, "split");
        Directory.CreateDirectory(splitDir);
        var manifest = new List<object>();
        var index = 0;

        foreach (var lvl in order)
        {
            var items = perLevel[lvl];
            var safe = new string(Path.GetFileNameWithoutExtension(lvl).Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c).ToArray());
            var stem = $"{index:000}_{safe}";
            index++;

            var w = new GlbWriter { ImageUriPrefix = "../" };
            var lo = new[] { float.MaxValue, float.MaxValue, float.MaxValue };
            var hi = new[] { float.MinValue, float.MinValue, float.MinValue };
            var used = 0;

            foreach (var (mesh, loc, rot, scale, matrixUE, source) in items)
            {
                var md = MaterialBinding.Apply(cache.Get(mesh),source?.OverrideMaterials);
                if (md is null) continue;
                w.AddInstance(w.AddMesh(md), loc, rot, scale, source?.SourceId ?? mesh, matrixUE,source);
                used++;

                // Exact transformed bounds: every vertex is pushed through the same placement
                // maths the geometry itself uses. Taking local bounds and translating them (the
                // obvious shortcut) is wrong for rotated instances, which is most of them, and
                // makes the manifest useless as a reference to check an import against.
                var r = UeFormat.RotationMatrix(rot?[0] ?? 0f, rot?[1] ?? 0f, rot?[2] ?? 0f);
                var s = new[] { scale?[0] ?? 1f, scale?[1] ?? 1f, scale?[2] ?? 1f };
                var t = new[] { loc?[0] ?? 0f, loc?[1] ?? 0f, loc?[2] ?? 0f };
                for (var i = 0; i < md.VertexCount; i++)
                {
                    var (px, py, pz) = TransformPoint(r, s, t,
                        md.Positions[i * 3], md.Positions[i * 3 + 1], md.Positions[i * 3 + 2], matrixUE);
                    if (px < lo[0]) lo[0] = px;
                    if (py < lo[1]) lo[1] = py;
                    if (pz < lo[2]) lo[2] = pz;
                    if (px > hi[0]) hi[0] = px;
                    if (py > hi[1]) hi[1] = py;
                    if (pz > hi[2]) hi[2] = pz;
                }
            }
            if (used == 0) continue;

            w.MaterialTextureFiles = _splitMaterials ?? new();
            var glbPath = Path.Combine(splitDir, stem + ".glb");
            w.Write(glbPath, $"{map}_{safe}");

            string uePath = null;
            if (uemodel)
            {
                var p = new List<float>();
                var n = new List<float>();
                var uv = new List<float>();
                var ix = new List<uint>();
                var mt = new List<UeFormat.Material>();
                foreach (var (mesh, loc, rot, scale, matrixUE, source) in items)
                {
                    var md = MaterialBinding.Apply(cache.Get(mesh),source?.OverrideMaterials);
                    if (md is null) continue;
                    AppendWorldGeometry(p, n, uv, ix, mt, md, loc, rot, scale, mesh, matrixUE);
                }
                if (ix.Count > 0)
                {
                    uePath = Path.Combine(splitDir, stem + ".uemodel");
                    UeFormat.Write(uePath, safe, $"/Game/Maps/{map}/{safe}",
                        new[]
                        {
                            new UeFormat.Lod
                            {
                                Positions = p.ToArray(),
                                Normals = n.ToArray(),
                                Uvs = uv.ToArray(),
                                Indices = ix.ToArray(),
                                Materials = mt,
                            },
                        });
                }
            }

            manifest.Add(new
            {
                file = stem,
                level = lvl,
                instances = used,
                ueBoundsMin = lo,
                ueBoundsMax = hi,
                ueSizeM = new[] { (hi[0] - lo[0]) / 100f, (hi[1] - lo[1]) / 100f, (hi[2] - lo[2]) / 100f },
                ueCentreM = new[] { (lo[0] + hi[0]) / 200f, (lo[1] + hi[1]) / 200f, (lo[2] + hi[2]) / 200f },
                blenderBoundsMinM = new[] { lo[0]/100f, -hi[1]/100f, lo[2]/100f },
                blenderBoundsMaxM = new[] { hi[0]/100f, -lo[1]/100f, hi[2]/100f },
                sourceLevel = lvl,
                glb = Path.GetFileName(glbPath),
                uemodel = uePath is null ? null : Path.GetFileName(uePath),
            });
            Console.WriteLine($"  [split] {stem}  {used,5} instances  " +
                              $"centre ({(lo[0] + hi[0]) / 200:0},{(lo[1] + hi[1]) / 200:0},{(lo[2] + hi[2]) / 200:0}) m");
        }

        File.WriteAllText(Path.Combine(splitDir, "manifest.json"),
            JsonConvert.SerializeObject(new
            {
                note = "One GLB per complete source level path. Mesh vertices are local and native affine node transforms are preserved. " +
                       "Bounds below are exact world-space geometry bounds; source metadata is retained in node extras.dfmap.",
                axisMap = "UE centimetres (x,y,z) -> glTF metres (x,z,y)/100; " +
                          "Blender metres (x,-y,z)/100; node transforms are preserved",
                totalVertices = steps,
                levels = manifest,
            }, Formatting.Indented));
        Console.WriteLine($"[split] wrote {manifest.Count} level files + manifest.json -> {splitDir}");
    }

    /// <summary>Material/texture mapping shared by every split file (set once per merge).</summary>
    private static Dictionary<string, (string BaseColor, string Normal, string Mra, float[] Tint)> _splitMaterials;

    /// <summary>
    /// Bake one instance into the merged world-space buffers used by the .uemodel export.
    /// The transform is applied here (rather than left on a node) because UEFormat models
    /// carry plain vertex data with no per-instance nodes.
    /// </summary>
    private static void AppendWorldGeometry(List<float> pos, List<float> nrm, List<float> uv, List<uint> idx,
                                            List<UeFormat.Material> mats, MeshData md,
                                            float[] loc, float[] rot, float[] scale, string name, float[] matrixUE = null)
    {
        var r = UeFormat.RotationMatrix(rot?[0] ?? 0f, rot?[1] ?? 0f, rot?[2] ?? 0f);
        var s = new[] { scale?[0] ?? 1f, scale?[1] ?? 1f, scale?[2] ?? 1f };
        var t = new[] { loc?[0] ?? 0f, loc?[1] ?? 0f, loc?[2] ?? 0f };

        var baseVertex = pos.Count / 3;
        var count = md.VertexCount;
        for (var i = 0; i < count; i++)
        {
            var (px, py, pz) = TransformPoint(r, s, t,
                md.Positions[i * 3], md.Positions[i * 3 + 1], md.Positions[i * 3 + 2], matrixUE);
            pos.Add(px);
            pos.Add(py);
            pos.Add(pz);

            var nx = md.Normals.Length > i * 3 + 2 ? md.Normals[i * 3] : 0f;
            var ny = md.Normals.Length > i * 3 + 2 ? md.Normals[i * 3 + 1] : 0f;
            var nz = md.Normals.Length > i * 3 + 2 ? md.Normals[i * 3 + 2] : 1f;
            nrm.Add((float)(r[0][0] * nx + r[0][1] * ny + r[0][2] * nz));
            nrm.Add((float)(r[1][0] * nx + r[1][1] * ny + r[1][2] * nz));
            nrm.Add((float)(r[2][0] * nx + r[2][1] * ny + r[2][2] * nz));

            uv.Add(md.Uvs.Length > i * 2 + 1 ? md.Uvs[i * 2] : 0f);
            uv.Add(md.Uvs.Length > i * 2 + 1 ? md.Uvs[i * 2 + 1] : 0f);
        }

        var firstFace = idx.Count / 3;
        foreach (var i in md.Indices) idx.Add((uint)(baseVertex + i));
        mats.Add(new UeFormat.Material
        {
            Name = md.Materials.Count > 0 && !string.IsNullOrEmpty(md.Materials[0])
                ? System.IO.Path.GetFileNameWithoutExtension(md.Materials[0])
                : System.IO.Path.GetFileNameWithoutExtension(md.Path),
            Path = md.Materials.Count > 0 && !string.IsNullOrEmpty(md.Materials[0])
                ? md.Materials[0]
                : md.Path,
            FirstIndex = firstFace,
            NumFaces = md.Indices.Length / 3,
        });
    }

    private static void WriteMarkdownReport(string path, MergeReport r)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"# dfmap merge report — {r.MapRoot}");
        sb.AppendLine();
        sb.AppendLine($"- policy: `{r.Policy}`");
        sb.AppendLine($"- levels found / kept: **{r.LevelsFound} / {r.LevelsIncluded}**");
        sb.AppendLine($"- instances: **{r.Instances}** placed");
        sb.AppendLine($"- unique meshes: **{r.UniqueMeshes}**, decoded: **{r.DecodedMeshes}**");
        sb.AppendLine($"- geometry: **{r.Vertices:n0} vertices / {r.Triangles:n0} triangles**");
        if (r.GlbMB > 0) sb.AppendLine($"- scene.glb: **{r.GlbMB} MB**");
        sb.AppendLine();
        sb.AppendLine("## world bounds");
        sb.AppendLine();
        sb.AppendLine("| space | min | max | size |");
        sb.AppendLine("|---|---|---|---|");
        if (r.WorldBoundsMinUE is not null)
        {
            sb.AppendLine($"| UE (cm) | ({r.WorldBoundsMinUE[0]:0}, {r.WorldBoundsMinUE[1]:0}, {r.WorldBoundsMinUE[2]:0}) " +
                          $"| ({r.WorldBoundsMaxUE[0]:0}, {r.WorldBoundsMaxUE[1]:0}, {r.WorldBoundsMaxUE[2]:0}) " +
                          $"| {(r.WorldBoundsMaxUE[0] - r.WorldBoundsMinUE[0]) / 100:0} x {(r.WorldBoundsMaxUE[1] - r.WorldBoundsMinUE[1]) / 100:0} x {(r.WorldBoundsMaxUE[2] - r.WorldBoundsMinUE[2]) / 100:0} m |");
            sb.AppendLine($"| glTF (m) | ({r.WorldBoundsMinGltf[0] / 100:0.0}, {r.WorldBoundsMinGltf[1] / 100:0.0}, {r.WorldBoundsMinGltf[2] / 100:0.0}) " +
                          $"| ({r.WorldBoundsMaxGltf[0] / 100:0.0}, {r.WorldBoundsMaxGltf[1] / 100:0.0}, {r.WorldBoundsMaxGltf[2] / 100:0.0}) | |");
        }
        sb.AppendLine();
        if (r.Warnings.Count > 0)
        {
            sb.AppendLine($"## warnings ({r.Warnings.Count})");
            sb.AppendLine();
            foreach (var w in r.Warnings.Take(50)) sb.AppendLine($"- {w}");
            sb.AppendLine();
        }
        sb.AppendLine("## level selection");
        sb.AppendLine();
        sb.AppendLine("| level | in | actors | inst | reason |");
        sb.AppendLine("|---|---|---|---|---|");
        foreach (var l in r.Levels.OrderByDescending(x => x.Include).ThenBy(x => x.Level))
            sb.AppendLine($"| `{l.Level.Replace("DeltaForce/Content/Maps/", "")}` | {(l.Include ? "yes" : "no")} | {l.Actors} | {l.Instances} | {l.Reason} |");
        File.WriteAllText(path, sb.ToString());
    }

    private static string GetOpt(string[] args, string name)
    {
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
