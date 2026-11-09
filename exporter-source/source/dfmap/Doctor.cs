using System.Runtime.InteropServices;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Dfmap;

public static class Doctor
{
    public static object Inspect(ConfigLoadResult loaded, bool mount = false)
    {
        var config = loaded.Config;
        var checks = new List<object>();
        var errors = new List<string>();
        void Check(string name, bool ok, string detail)
        {
            checks.Add(new { name, ok, detail });
            if (!ok) errors.Add(name);
        }
        Check("game_root", !string.IsNullOrWhiteSpace(config.PaksDirectory) && Directory.Exists(config.PaksDirectory), config.PaksDirectory);
        Check("profile", true, config.Game);
        var keyExists = !string.IsNullOrWhiteSpace(config.KeyFile) && File.Exists(config.KeyFile);
        Check("key_file", keyExists, config.KeyFile);
        int? dynamicKeys = null;
        string keyVersion = null;
        if (keyExists)
        {
            try
            {
                var root = JObject.Parse(File.ReadAllText(config.KeyFile).TrimStart('\uFEFF'));
                static bool HexKey(JToken token)
                {
                    if (token?.Type != JTokenType.String) return false;
                    var value = token.Value<string>();
                    if (value!.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) value = value[2..];
                    return value.Length == 64 && value.All(Uri.IsHexDigit);
                }
                var entries = root["Keys"] ?? root["keys"];
                var main = root["MainKey"] ?? root["mainKey"];
                var ok = HexKey(main) && (entries is null || entries is JArray);
                if (entries is JArray list)
                {
                    dynamicKeys = list.Count;
                    ok &= list.All(item => item is JObject && HexKey(item["key"] ?? item["Key"]) &&
                        Guid.TryParse((item["guid"] ?? item["Guid"])?.Value<string>(), out _));
                }
                keyVersion = (root["Version"] ?? root["version"])?.Value<string>();
                Check("key_structure", ok, ok ? "Main key and dynamic entries have valid shapes; values are redacted." : "Expected a 64-digit hexadecimal MainKey and optional Keys entries with guid/key. Values are not shown.");
            }
            catch (JsonReaderException ex)
            {
                Check("key_structure", false, $"Key JSON is invalid at line {ex.LineNumber}, position {ex.LinePosition}; contents are not shown.");
            }
            catch (Exception ex)
            {
                Check("key_structure", false, $"Key file could not be checked ({ex.GetType().Name}); contents are not shown.");
            }
        }
        foreach (var dll in new[] { "Detex.dll", "zlib-ng2.dll", "oodle-data-shared.dll" })
        {
            var path = Path.Combine(AppContext.BaseDirectory, dll);
            if (!File.Exists(path)) path = Path.Combine(Directory.GetCurrentDirectory(), dll);
            Check("codec_" + dll, File.Exists(path), path);
        }
        object mounted = null;
        if (mount && errors.Count == 0)
        {
            try
            {
                using var provider = Mount.Create(config, AesKeySet.Load(config.KeyFile), verbose: false);
                mounted = new { archives = provider.MountedVfs.Count, virtual_files = provider.Files.Count };
                Check("mount", provider.MountedVfs.Count > 0 && provider.Files.Count > 0, "Explicit archive mount verification completed.");
            }
            catch (Exception ex)
            {
                Check("mount", false, $"Mount failed ({ex.GetType().Name}); inspect the game root, version/profile and key set.");
            }
        }
        return new
        {
            ok = errors.Count == 0,
            mode = mount ? "explicit mount" : "offline",
            config_source = loaded.SourcePath,
            config_selection = loaded.Selection,
            game_root = config.PaksDirectory,
            key_file = config.KeyFile,
            key_version = keyVersion,
            dynamic_key_count = dynamicKeys,
            runtime = RuntimeInformation.FrameworkDescription,
            architecture = RuntimeInformation.ProcessArchitecture.ToString(),
            checks, warnings = loaded.Warnings, failed_checks = errors, mount = mounted,
            scope = "Checks file existence and key structure; offline mode neither mounts archives nor downloads keys/codecs."
        };
    }

    public static int Run(ConfigLoadResult loaded, string[] args)
    {
        if (args.Any(a => a != "--mount" && a != "--out" && !IsOutputPath(args, a)))
            throw new ArgumentException("usage: dfmap [--config file] doctor [--mount] [--out report.json]");
        var report = Inspect(loaded, args.Contains("--mount"));
        var json = JsonConvert.SerializeObject(report, Formatting.Indented);
        var outIndex = Array.IndexOf(args, "--out");
        if (outIndex >= 0)
        {
            if (outIndex + 1 >= args.Length || args[outIndex + 1].StartsWith("--")) throw new ArgumentException("--out requires a report path.");
            var path = Path.GetFullPath(ConfigService.NormalizePath(args[outIndex + 1]));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, json, new System.Text.UTF8Encoding(false));
        }
        Console.WriteLine(json);
        return JObject.Parse(json)["ok"]!.Value<bool>() ? 0 : 1;
    }

    private static bool IsOutputPath(string[] args, string value)
    {
        var index = Array.IndexOf(args, "--out");
        return index >= 0 && index + 1 < args.Length && args[index + 1] == value;
    }
}
