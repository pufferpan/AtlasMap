using CUE4Parse.FileProvider;
using Newtonsoft.Json;

namespace Dfmap;

/// <summary>
/// Map-level inventory: walk every level package of a map family, read its
/// LevelBounds cell, and reconstruct the real world grid the map is tiled on.
/// </summary>
public static class MapTools
{
    /// <summary>
    /// List the immediate sub-directories under a virtual path prefix with file counts and
    /// sizes. This is the "browse the Content tree" command - it makes it obvious which
    /// folders hold which kinds of assets.
    /// </summary>
    public static int CmdDirs(IFileProvider provider, string[] args)
    {
        var prefix = args.Length > 0 ? args[0].TrimEnd('/') + "/" : "";
        var depth = args.Length > 1 ? int.Parse(args[1]) : 1;
        var minFiles = args.Length > 2 ? int.Parse(args[2]) : 1;

        var buckets = new Dictionary<string, (int Files, long Bytes)>(StringComparer.OrdinalIgnoreCase);
        foreach (var f in provider.Files.Values)
        {
            if (!f.Path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
            var rest = f.Path[prefix.Length..];
            var parts = rest.Split('/');
            if (parts.Length <= depth) continue;                      // a file directly in the prefix
            var key = string.Join("/", parts.Take(depth)) + "/";
            if (buckets.TryGetValue(key, out var cur))
                buckets[key] = (cur.Files + 1, cur.Bytes + f.Size);
            else
                buckets[key] = (1, f.Size);
        }
        // files sitting directly under the prefix
        var direct = provider.Files.Values.Count(f =>
        {
            if (!f.Path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return false;
            return f.Path[prefix.Length..].Split('/').Length == 1;
        });

        Console.WriteLine($"prefix: {prefix}   ({provider.Files.Values.Count(f => f.Path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)):n0} files total)");
        if (direct > 0) Console.WriteLine($"  {direct,8:n0} files  <directly here>");
        foreach (var kv in buckets.OrderByDescending(k => k.Value.Files))
        {
            if (kv.Value.Files < minFiles) continue;
            Console.WriteLine($"  {kv.Value.Files,8:n0} files  {kv.Value.Bytes / 1048576.0,10:n1} MB   {kv.Key}");
        }
        return 0;
    }

    public static int CmdScan(IFileProvider provider, string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap scan <pathPrefix> [outJson] [maxLevels]"); return 2; }
        var prefix = args[0];
        var outFile = args.Length > 1 ? args[1] : null;
        var maxLevels = args.Length > 2 ? int.Parse(args[2]) : int.MaxValue;

        var levelPaths = provider.Files.Keys
            .Where(p => p.EndsWith(".umap", StringComparison.OrdinalIgnoreCase)
                        && p.Contains(prefix, StringComparison.OrdinalIgnoreCase))
            .OrderBy(p => p, StringComparer.OrdinalIgnoreCase)
            .ToList();

        Console.WriteLine($"{levelPaths.Count} level packages match '{prefix}'");

        var results = new List<LevelSummary>();
        var t0 = DateTime.UtcNow;
        for (var i = 0; i < levelPaths.Count && i < maxLevels; i++)
        {
            var p = levelPaths[i];
            LevelSummary s;
            try { s = Levels.Extract(provider, p, collectInstances: false); }
            catch (Exception ex)
            {
                s = new LevelSummary { Level = p, Errors = { ex.GetType().Name + ": " + ex.Message } };
            }
            results.Add(s);
            var c = s.BoundsCenter;
            Console.WriteLine($"[{i + 1,4}/{Math.Min(levelPaths.Count, maxLevels)}] " +
                              $"actors={s.ActorCount,6} inst={s.InstanceCount,6} " +
                              $"cell={(c is null ? "-" : $"{c[0]:0},{c[1]:0}"),-18} " +
                              p.Replace("DeltaForce/Content/Maps/", ""));
        }

        Console.WriteLine($"\nscanned in {(DateTime.UtcNow - t0).TotalSeconds:0.0}s");

        // --- reconstruct the world grid from LevelBounds centres ---
        var cells = results.Where(r => r.BoundsCenter is not null)
                           .Select(r => (X: MathF.Round(r.BoundsCenter[0]), Y: MathF.Round(r.BoundsCenter[1])))
                           .ToList();
        if (cells.Count > 1)
        {
            var xs = cells.Select(c => c.X).Distinct().OrderBy(v => v).ToList();
            var ys = cells.Select(c => c.Y).Distinct().OrderBy(v => v).ToList();
            var stepX = MinStep(xs);
            var stepY = MinStep(ys);
            Console.WriteLine($"\n== world grid ==");
            Console.WriteLine($"distinct cell X: {xs.Count}  range {xs.First():0} .. {xs.Last():0}");
            Console.WriteLine($"distinct cell Y: {ys.Count}  range {ys.First():0} .. {ys.Last():0}");
            Console.WriteLine($"smallest X step: {stepX:0}   smallest Y step: {stepY:0}");
            Console.WriteLine($"=> implied cell size ~ {stepX / 100:0.##} m x {stepY / 100:0.##} m");
        }

        var totalInst = results.Sum(r => r.InstanceCount);
        Console.WriteLine($"\ntotal mesh instances across {results.Count} levels: {totalInst}");

        if (outFile is not null)
        {
            File.WriteAllText(outFile, JsonConvert.SerializeObject(results, Formatting.Indented));
            Console.WriteLine($"wrote {outFile} ({new FileInfo(outFile).Length / 1024} KB)");
        }
        return 0;
    }

    private static float MinStep(List<float> sorted)
    {
        var best = float.MaxValue;
        for (var i = 1; i < sorted.Count; i++)
        {
            var d = MathF.Abs(sorted[i] - sorted[i - 1]);
            if (d > 1f && d < best) best = d;
        }
        return best == float.MaxValue ? 0f : best;
    }
}
