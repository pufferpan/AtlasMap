using System.Diagnostics;
using CUE4Parse;
using CUE4Parse.Encryption.Aes;
using Serilog;
using CUE4Parse.FileProvider;
using CUE4Parse.FileProvider.Vfs;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;

namespace Dfmap;

/// <summary>AES key set published for Game (MainKey + per-pak-GUID dynamic keys).</summary>
public sealed class AesKeySet
{
    public string Version { get; set; }
    public string MainKey { get; set; }
    public List<AesKeyEntry> Keys { get; set; } = new();

    public static AesKeySet Load(string path)
    {
        var set = JsonConvert.DeserializeObject<AesKeySet>(File.ReadAllText(path));
        if (set is null) throw new InvalidDataException($"cannot parse key file: {path}");
        if (string.IsNullOrWhiteSpace(set.MainKey)) throw new InvalidDataException("key file has no MainKey");
        return set;
    }

    public IEnumerable<KeyValuePair<FGuid, FAesKey>> ToPairs()
    {
        if (!string.IsNullOrWhiteSpace(MainKey))
            yield return new KeyValuePair<FGuid, FAesKey>(new FGuid(0u), new FAesKey(MainKey));
        foreach (var k in Keys)
        {
            if (string.IsNullOrWhiteSpace(k.Key) || string.IsNullOrWhiteSpace(k.Guid)) continue;
            yield return new KeyValuePair<FGuid, FAesKey>(new FGuid(k.Guid), new FAesKey(k.Key));
        }
    }
}

public sealed class AesKeyEntry
{
    [JsonProperty("key")] public string Key { get; set; }
    [JsonProperty("guid")] public string Guid { get; set; }
}

public sealed class GameConfig
{
    /// <summary>Game root (NOT just Content\Paks): the map content also lives in
    /// PackContent\Paks and in the Saved\Dolphin patch paks.</summary>
    public string PaksDirectory { get; set; } =
        @"E:\WeGameApps\rail_apps\DeltaForce(2001918)";

    /// <summary>FModel scans the whole game root, so we do too.</summary>
    public bool Recursive { get; set; } = true;

    public string KeyFile { get; set; }
    public string KeyUrl { get; set; } =
        "https://raw.githubusercontent.com/Alpace123/AESkey/refs/heads/main/AESKey1.json";
    public string OodlePath { get; set; }

    /// <summary>
    /// Which CUE4Parse game profile to use. GAME_DeltaForce is REQUIRED: with GAME_UE4_27
    /// zero archives mount, because Game's pak footer drops the EncryptionKeyGuid /
    /// bEncryptedIndex fields and only the dedicated profile parses it.
    /// </summary>
    public string Game { get; set; } = "GAME_DeltaForce";

    /// <summary>
    /// Profile used ONLY while deserializing static-mesh packages (see GameSwapScope).
    /// Game's streamed LOD layout matches the Tencent GameForPeace reader, which
    /// CUE4Parse selects by game id; mounting must stay on GAME_DeltaForce.
    /// </summary>
    public string MeshGame { get; set; }

    /// <summary>
    /// Version option overrides handed to VersionContainer. CUE4Parse branches on option
    /// lookups such as "StaticMesh.UseNewCookedFormat"; if the profile does not set one,
    /// the wrong branch is taken and the parse throws.
    /// </summary>
    public Dictionary<string, bool> OptionOverrides { get; set; }

    /// <summary>Where the key file lives; defaults next to this tool.</summary>
    public static string DefaultKeyFile =>
        Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "config", "AESKey1.json");
}

public static class Mount
{
    public static DefaultFileProvider Create(GameConfig cfg, AesKeySet keys, bool verbose = true)
    {
        // CLI, GUI and embedded audits must all recognize the custom classes.
        DeltaForceTypes.Register();
        if (!Directory.Exists(cfg.PaksDirectory))
            throw new DirectoryNotFoundException($"game directory not found: {cfg.PaksDirectory}");

        // CUE4Parse swallows per-export deserialization errors and returns a partially
        // built object; route its Serilog output to the console so we can see them.
        if (Environment.GetEnvironmentVariable("ATLASMAP_LOG") == "1")
            CUE4ParseLog.UseLogger(new LoggerConfiguration()
                .MinimumLevel.Debug()
                .WriteTo.Console(outputTemplate: "[cue4parse {Level:u3}] {Message:lj}{NewLine}{Exception}")
                .CreateLogger());

        // FModel runs this game with a manual UE 4.27 version; the dedicated DeltaForce
        // profile changes struct deserialization, so it is selectable.
        var game = ConfigService.ParseGameProfile(cfg.Game);
        if (!string.IsNullOrEmpty(cfg.MeshGame)) ConfigService.ParseGameProfile(cfg.MeshGame, "MeshGame");
        var versions = new VersionContainer(game, optionOverrides: cfg.OptionOverrides);
        if (verbose) Console.Error.WriteLine($"[atlas] game profile: {game}");
        if (verbose && cfg.OptionOverrides is { Count: > 0 })
            Console.Error.WriteLine($"[atlas] option overrides: " +
                string.Join(", ", cfg.OptionOverrides.Select(kv => $"{kv.Key}={kv.Value}")));
        var search = cfg.Recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;
        var provider = new DefaultFileProvider(
            cfg.PaksDirectory, search, versions, StringComparer.OrdinalIgnoreCase);

        var sw = Stopwatch.StartNew();
        provider.Initialize();
        if (verbose) Console.Error.WriteLine($"[atlas] scanned '{cfg.PaksDirectory}' ({search}) in {sw.ElapsedMilliseconds} ms");

        sw.Restart();
        var matched = provider.SubmitKeys(keys.ToPairs());
        if (verbose)
            Console.Error.WriteLine($"[atlas] submitted {keys.Keys.Count + 1} keys, " +
                                    $"{matched} archives accepted a key, in {sw.ElapsedMilliseconds} ms");

        sw.Restart();
        var mounted = provider.Mount();
        if (verbose)
            Console.Error.WriteLine($"[atlas] mounted {mounted} archives, " +
                                    $"{provider.Files.Count} files, {provider.MountedVfs.Count} vfs, " +
                                    $"in {sw.ElapsedMilliseconds} ms");

        if (!string.IsNullOrEmpty(cfg.MeshGame) && !string.Equals(cfg.MeshGame, cfg.Game, StringComparison.OrdinalIgnoreCase))
            Console.Error.WriteLine($"[atlas] static meshes will be read with profile {cfg.MeshGame} " +
                                    $"(mount and levels stay on {game}); see MeshGame docs");

        return provider;
    }
}
