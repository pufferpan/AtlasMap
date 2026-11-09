using System.Globalization;
using System.Text;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;

namespace Dfmap;

public sealed class ConfigLoadResult
{
    public GameConfig Config { get; init; }
    public string SourcePath { get; init; }
    public string Selection { get; init; }
    public List<string> Warnings { get; init; } = new();
}

/// <summary>One configuration loader for CLI, GUI and offline diagnostics.</summary>
public static class ConfigService
{
    public static string NormalizePath(string path)
    {
        if (path is null) return null;
        static bool Ignorable(char c) => char.IsWhiteSpace(c) || char.IsControl(c)
            || char.GetUnicodeCategory(c) == UnicodeCategory.Format;
        var first = 0;
        var last = path.Length;
        while (first < last && Ignorable(path[first])) first++;
        while (last > first && Ignorable(path[last - 1])) last--;
        return path[first..last];
    }

    public static EGame ParseGameProfile(string value, string field = "Game")
    {
        value = NormalizePath(value);
        if (string.IsNullOrWhiteSpace(value) || !value.StartsWith("GAME_", StringComparison.OrdinalIgnoreCase)
            || !Enum.TryParse<EGame>(value, true, out var game) || !Enum.IsDefined(game))
            throw new InvalidDataException($"Invalid {field} profile '{value}'. Game normally requires GAME_DeltaForce; no fallback profile was selected.");
        return game;
    }

    public static GameConfig Normalize(GameConfig source, string baseDirectory = null)
    {
        ArgumentNullException.ThrowIfNull(source);
        var config = JsonConvert.DeserializeObject<GameConfig>(JsonConvert.SerializeObject(source));
        var root = Path.GetFullPath(baseDirectory ?? Directory.GetCurrentDirectory());
        string Resolve(string value)
        {
            value = NormalizePath(value);
            if (string.IsNullOrEmpty(value)) return value;
            return Path.GetFullPath(value, root);
        }
        config.PaksDirectory = Resolve(config.PaksDirectory);
        config.KeyFile = Resolve(config.KeyFile ?? GameConfig.DefaultKeyFile);
        config.OodlePath = Resolve(config.OodlePath);
        config.Game = NormalizePath(config.Game);
        config.MeshGame = NormalizePath(config.MeshGame);
        ParseGameProfile(config.Game);
        if (!string.IsNullOrEmpty(config.MeshGame)) ParseGameProfile(config.MeshGame, "MeshGame");
        return config;
    }

    /// <summary>Explicit path > ATLASMAP_CONFIG > executable dfmap.json > working-directory dfmap.json > defaults.</summary>
    public static ConfigLoadResult Load(string explicitPath = null, string appDirectory = null,
        string workingDirectory = null, bool environmentOverrides = true)
    {
        var app = Path.GetFullPath(appDirectory ?? AppContext.BaseDirectory);
        var cwd = Path.GetFullPath(workingDirectory ?? Directory.GetCurrentDirectory());
        string path = NormalizePath(explicitPath);
        var selection = "explicit";
        var warnings = new List<string>();
        if (string.IsNullOrEmpty(path) && environmentOverrides)
        {
            path = NormalizePath(Environment.GetEnvironmentVariable("ATLASMAP_CONFIG"));
            selection = "ATLASMAP_CONFIG";
        }
        if (!string.IsNullOrEmpty(path))
        {
            path = Path.GetFullPath(path, cwd);
            if (!File.Exists(path)) throw new FileNotFoundException($"Selected configuration file does not exist: {path}", path);
        }
        else
        {
            var byExe = Path.Combine(app, "dfmap.json");
            var byCwd = Path.Combine(cwd, "dfmap.json");
            if (File.Exists(byExe)) { path = byExe; selection = "executable directory"; }
            else if (File.Exists(byCwd)) { path = byCwd; selection = "working directory"; }
            else { path = null; selection = "built-in defaults"; }
        }

        GameConfig config;
        if (path is null)
        {
            config = new GameConfig();
            warnings.Add("No dfmap.json was found; built-in defaults are in use. Set the game root and key file before exporting.");
        }
        else
        {
            try
            {
                var text = File.ReadAllText(path, Encoding.UTF8).TrimStart('\uFEFF');
                config = JsonConvert.DeserializeObject<GameConfig>(text)
                    ?? throw new InvalidDataException($"Configuration must contain a JSON object: {path}");
            }
            catch (JsonException ex)
            {
                throw new InvalidDataException($"Invalid configuration JSON: {path}. {ex.Message} " +
                    "Windows paths in JSON must use doubled backslashes (E:\\\\Games) or forward slashes (E:/Games). " +
                    "Use the GUI Save configuration action to avoid manual escaping errors.", ex);
            }
        }
        var originalPaths = new[] { config.PaksDirectory, config.KeyFile, config.OodlePath };
        if (originalPaths.Any(p => p is not null && p != NormalizePath(p)))
            warnings.Add("Whitespace or invisible directional/format marks at a path boundary were removed.");
        if (environmentOverrides && Environment.GetEnvironmentVariable("ATLASMAP_GAME") is { Length: > 0 } game)
        {
            config.Game = game;
            warnings.Add("Game profile was overridden by ATLASMAP_GAME.");
        }
        config = Normalize(config, path is null ? cwd : Path.GetDirectoryName(path));
        if (!config.Recursive) warnings.Add("Recursive scanning is disabled; Game patch and PackContent archives may be missed.");
        if (!string.Equals(config.Game, "GAME_DeltaForce", StringComparison.OrdinalIgnoreCase))
            warnings.Add("The configured mount profile is not GAME_DeltaForce; Game archive mounting normally requires it.");
        return new ConfigLoadResult { Config = config, SourcePath = path, Selection = selection, Warnings = warnings };
    }

    public static void Save(string path, GameConfig config)
    {
        path = Path.GetFullPath(NormalizePath(path));
        var normalized = Normalize(config, Path.GetDirectoryName(path));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonConvert.SerializeObject(normalized, Formatting.Indented), new UTF8Encoding(false));
        File.Move(temporary, path, true);
    }

    public static string Fingerprint(GameConfig config) => JsonConvert.SerializeObject(config);

    public static (string ConfigPath, string[] Arguments) ExtractConfigArgument(string[] args)
    {
        var remaining = new List<string>();
        string config = null;
        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] == "--config")
            {
                if (config is not null) throw new ArgumentException("--config may be supplied only once.");
                if (++i >= args.Length || string.IsNullOrWhiteSpace(NormalizePath(args[i])) || args[i].StartsWith("--"))
                    throw new ArgumentException("--config requires a configuration file path.");
                config = args[i];
            }
            else if (args[i].StartsWith("--config=", StringComparison.Ordinal))
            {
                if (config is not null) throw new ArgumentException("--config may be supplied only once.");
                config = args[i][9..];
                if (string.IsNullOrWhiteSpace(NormalizePath(config))) throw new ArgumentException("--config requires a configuration file path.");
            }
            else remaining.Add(args[i]);
        }
        return (config, remaining.ToArray());
    }
}
