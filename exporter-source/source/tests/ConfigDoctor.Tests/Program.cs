using System.Reflection;
using System.Text;
using CUE4Parse.FileProvider;
using Dfmap;
using Newtonsoft.Json;

var root = Path.Combine(Path.GetTempPath(), "dfmap-config-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var tests = new List<object>();
var originalConfig = Environment.GetEnvironmentVariable("ATLASMAP_CONFIG");
var originalGame = Environment.GetEnvironmentVariable("ATLASMAP_GAME");
Environment.SetEnvironmentVariable("ATLASMAP_CONFIG", null);
Environment.SetEnvironmentVariable("ATLASMAP_GAME", null);
try
{
    string Folder(string name) { var p = Path.Combine(root, name); Directory.CreateDirectory(p); return p; }
    void Require(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
    void Test(string name, Action action) { action(); tests.Add(new { name, passed = true }); Console.WriteLine("PASS " + name); }
    var app = Folder("application");
    var cwd = Folder("working");
    var gameRoot = Folder("game root");
    var fakeKey = "0x" + new string('A', 64);
    var keyPath = Path.Combine(root, "keys.json");
    File.WriteAllText(keyPath, JsonConvert.SerializeObject(new { MainKey = fakeKey, Keys = new[] { new { guid = Guid.Empty.ToString("N"), key = fakeKey } } }));
    GameConfig Config(string suffix = "") => new() { PaksDirectory = gameRoot + suffix, KeyFile = keyPath, Game = "GAME_DeltaForce" };
    var appPath = Path.Combine(app, "dfmap.json");
    var cwdPath = Path.Combine(cwd, "dfmap.json");
    ConfigService.Save(appPath, Config());
    ConfigService.Save(cwdPath, Config("-working"));

    Test("executable config wins over working config", () =>
        Require(ConfigService.Load(appDirectory: app, workingDirectory: cwd).Config.PaksDirectory == gameRoot, "Wrong implicit precedence"));
    Test("explicit config wins over executable config", () =>
        Require(ConfigService.Load(cwdPath, appDirectory: app, workingDirectory: cwd).Config.PaksDirectory.EndsWith("-working"), "Explicit config ignored"));
    Test("ATLASMAP_CONFIG wins over executable config but not explicit", () =>
    {
        Environment.SetEnvironmentVariable("ATLASMAP_CONFIG", cwdPath);
        Require(ConfigService.Load(appDirectory: app, workingDirectory: cwd).SourcePath == cwdPath, "Environment config ignored");
        Require(ConfigService.Load(appPath, appDirectory: app, workingDirectory: cwd).SourcePath == appPath, "Environment overrode explicit config");
        Environment.SetEnvironmentVariable("ATLASMAP_CONFIG", null);
    });
    Test("missing explicit config fails instead of silently falling back", () =>
    {
        try { ConfigService.Load(Path.Combine(root, "missing.json"), appDirectory: app); throw new Exception("Missing config accepted"); }
        catch (FileNotFoundException) { }
    });
    Test("BOM and boundary direction marks are normalized", () =>
    {
        var file = Path.Combine(root, "bom.json");
        File.WriteAllText(file, "\uFEFF" + JsonConvert.SerializeObject(new { PaksDirectory = "\u202A" + gameRoot + "\u202C", KeyFile = "\uFEFF" + keyPath, Game = "GAME_DeltaForce" }), new UTF8Encoding(true));
        var result = ConfigService.Load(file);
        Require(result.Config.PaksDirectory == gameRoot && result.Config.KeyFile == keyPath, "Boundary marks survived");
        Require(result.Warnings.Any(x => x.Contains("invisible")), "Normalization was not reported");
    });
    Test("relative paths resolve beside selected config", () =>
    {
        var file = Path.Combine(cwd, "relative.json");
        File.WriteAllText(file, "{\"PaksDirectory\":\"game\",\"KeyFile\":\"keys.json\"}");
        var result = ConfigService.Load(file);
        Require(result.Config.PaksDirectory == Path.Combine(cwd, "game"), "Game path used process CWD");
        Require(result.Config.KeyFile == Path.Combine(cwd, "keys.json"), "Key path used process CWD");
    });
    Test("invalid profile never falls back to UE4_27", () =>
    {
        foreach (var bad in new[] { "GAME_DeltaFrce", "999", "" })
        {
            try { ConfigService.Normalize(new GameConfig { Game = bad }); throw new Exception("Bad profile accepted"); }
            catch (InvalidDataException) { }
        }
    });
    Test("invalid Windows JSON gives escaping guidance", () =>
    {
        var file = Path.Combine(root, "bad.json");
        File.WriteAllText(file, "{\"PaksDirectory\":\"E:\\WeGameApps\"}");
        try { ConfigService.Load(file); throw new Exception("Bad JSON accepted"); }
        catch (InvalidDataException ex) { Require(ex.Message.Contains("backslashes") && ex.Message.Contains("E:/Games"), "Repair guidance absent"); }
    });
    Test("Save serializer roundtrips paths without manual escaping", () =>
    {
        var file = Path.Combine(root, "saved.json");
        ConfigService.Save(file, Config());
        Require(ConfigService.Load(file).Config.KeyFile == keyPath, "Saved config could not be loaded");
    });
    Test("global --config parsing preserves other arguments", () =>
    {
        var parsed = ConfigService.ExtractConfigArgument(new[] { "merge", "Iceland", "--config", appPath, "out folder", "--split" });
        Require(parsed.ConfigPath == appPath && parsed.Arguments.SequenceEqual(new[] { "merge", "Iceland", "out folder", "--split" }), "Arguments were reordered or lost");
        try { ConfigService.ExtractConfigArgument(new[] { "--config" }); throw new Exception("Missing argument accepted"); } catch (ArgumentException) { }
        try { ConfigService.ExtractConfigArgument(new[] { "--config=a", "--config=b" }); throw new Exception("Duplicate config accepted"); } catch (ArgumentException) { }
    });
    Test("offline doctor redacts all key values", () =>
    {
        var json = JsonConvert.SerializeObject(Doctor.Inspect(ConfigService.Load(appPath)));
        Require(!json.Contains(fakeKey) && !json.Contains(new string('A', 64)), "Key leaked into report");
        Require(json.Contains("offline") && json.Contains("dynamic_key_count"), "Doctor summary absent");
    });
    Test("malformed key doctor report does not echo file contents", () =>
    {
        var malformed = Path.Combine(root, "malformed-keys.json");
        File.WriteAllText(malformed, "{\"MainKey\":\"" + fakeKey + "\",BROKEN}");
        var config = Config(); config.KeyFile = malformed;
        var json = JsonConvert.SerializeObject(Doctor.Inspect(new ConfigLoadResult { Config = config }));
        Require(!json.Contains(fakeKey) && json.Contains("key_structure"), "Malformed key data leaked");
    });
    Test("mounted provider rejects silent configuration changes", () =>
    {
        Dfmap.Program.Configure(Config());
        var proxy = DispatchProxy.Create<IFileProvider, ProviderProxy>();
        typeof(Dfmap.Program).GetField("_sharedProvider", BindingFlags.NonPublic | BindingFlags.Static)!.SetValue(null, proxy);
        try { Dfmap.Program.Configure(Config("-different")); throw new Exception("Live provider changed silently"); }
        catch (InvalidOperationException) { }
        Dfmap.Program.Configure(Config("-different"), resetSharedProvider: true);
        Require(((ProviderProxy)(object)proxy).Disposed, "Explicit reset did not dispose old provider");
    });
    Test("embedding configuration snapshot cannot mutate active config", () =>
    {
        Dfmap.Program.Configure(Config());
        var snapshot = Dfmap.Program.CurrentConfiguration(); snapshot.Config.Game = "BROKEN";
        Require(Dfmap.Program.CurrentConfiguration().Config.Game == "GAME_DeltaForce", "Returned mutable active instance");
    });
    Console.WriteLine(JsonConvert.SerializeObject(new { passed = tests.Count, tests }, Formatting.Indented));
}
finally
{
    Environment.SetEnvironmentVariable("ATLASMAP_CONFIG", originalConfig);
    Environment.SetEnvironmentVariable("ATLASMAP_GAME", originalGame);
    // Delete only this uniquely named test fixture directory.
    if (Directory.Exists(root)) Directory.Delete(root, true);
}

public class ProviderProxy : DispatchProxy
{
    public bool Disposed { get; private set; }
    protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
    {
        if (targetMethod?.Name == nameof(IDisposable.Dispose)) { Disposed = true; return null; }
        throw new NotSupportedException("This test provider is never mounted or queried.");
    }
}
