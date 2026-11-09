using System.Reflection;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports;
using Newtonsoft.Json;

namespace Dfmap;

/// <summary>Reflective API discovery + raw object dumping, so the tool is written
/// against the real CUE4Parse surface instead of guessed signatures.</summary>
public static class Inspect
{
    public static Assembly Cue4Asm => typeof(UObject).Assembly;

    /// <summary>All CUE4Parse assemblies that are actually loaded (core + Conversion + game types).</summary>
    public static IEnumerable<Assembly> AllAsms()
    {
        var seen = new HashSet<string>();
        foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
        {
            var n = a.GetName().Name ?? "";
            if (n.StartsWith("CUE4Parse", StringComparison.OrdinalIgnoreCase) && seen.Add(n)) yield return a;
        }
        foreach (var extra in new[] { "CUE4Parse", "CUE4Parse-Conversion" })
        {
            if (seen.Contains(extra)) continue;
            Assembly a = null;
            try { a = Assembly.Load(extra); } catch { }
            if (a is not null) yield return a;
        }
    }

    public static int CmdApi(string[] args)
    {
        var needle = args.Length > 0 ? args[0] : "";
        var asms = AllAsms().ToList();
        Console.WriteLine($"assemblies: {string.Join(", ", asms.Select(a => a.GetName().Name + " " + a.GetName().Version))}");

        var types = asms.SelectMany(a =>
        {
            try { return a.GetExportedTypes(); }
            catch { return Array.Empty<Type>(); }
        }).ToArray();

        // Method-name search: lets us find extension helpers whose declaring type name
        // gives no hint (e.g. the texture Decode extension).
        var mHits = new List<string>();
        foreach (var t in types)
        {
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                if (m.IsSpecialName || !m.Name.Contains(needle, StringComparison.OrdinalIgnoreCase)) continue;
                var ext = m.IsDefined(typeof(System.Runtime.CompilerServices.ExtensionAttribute), false) ? " [extension]" : "";
                mHits.Add($"  {t.FullName}::{m.Name}({string.Join(", ", m.GetParameters().Select(P))}) -> {S(m.ReturnType)}{ext}");
            }
        }
        if (mHits.Count > 0)
        {
            Console.WriteLine($"\n### methods matching \"{needle}\" ({mHits.Count})");
            foreach (var h in mHits.Take(40)) Console.WriteLine(h);
            return 0;
        }

        foreach (var t in types
                     .Where(t => t.Name.Contains(needle, StringComparison.OrdinalIgnoreCase)
                                 || (t.FullName?.Contains(needle, StringComparison.OrdinalIgnoreCase) ?? false))
                     .OrderBy(t => t.FullName))
        {
            Console.WriteLine($"\n### {t.FullName}");
            if (t.IsEnum)
            {
                Console.WriteLine("    " + string.Join(", ", Enum.GetNames(t).Take(40)));
                continue;
            }
            foreach (var c in t.GetConstructors(BindingFlags.Public | BindingFlags.Instance))
                Console.WriteLine("    .ctor(" + string.Join(", ", c.GetParameters().Select(P)) + ")");
            foreach (var m in t.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                         .OrderBy(m => m.Name))
            {
                switch (m)
                {
                    case MethodInfo mi when !mi.IsSpecialName:
                        Console.WriteLine($"    {S(mi.ReturnType)} {mi.Name}({string.Join(", ", mi.GetParameters().Select(P))})");
                        break;
                    case PropertyInfo pi:
                        Console.WriteLine($"    prop {S(pi.PropertyType)} {pi.Name}");
                        break;
                    case FieldInfo fi:
                        Console.WriteLine($"    fld  {S(fi.FieldType)} {fi.Name}");
                        break;
                }
            }
        }
        return 0;
    }

    /// <summary>Serialize every export of a package to JSON (CUE4Parse's own converters).</summary>
    public static int CmdDump(IFileProvider provider, string path, string outFile)
    {
        var pkg = provider.LoadPackage(path);
        Console.WriteLine($"package {pkg.Name}: {pkg.ExportMapLength} exports, canDeserialize={pkg.CanDeserialize}");

        var settings = BuildJsonSettings(provider);
        var exports = new List<object>();
        foreach (var lazy in pkg.ExportsLazy)
        {
            UObject obj;
            try { obj = lazy.Value; }
            catch (Exception ex) { exports.Add(new { error = ex.Message }); continue; }
            if (obj is null) continue;
            try
            {
                exports.Add(new
                {
                    type = obj.ExportType,
                    name = obj.Name,
                    value = obj
                });
            }
            catch (Exception ex)
            {
                exports.Add(new { type = obj.ExportType, name = obj.Name, error = ex.Message });
            }
        }

        File.WriteAllText(outFile, JsonConvert.SerializeObject(exports, Formatting.Indented, settings));
        Console.WriteLine($"wrote {outFile}  ({new FileInfo(outFile).Length / 1024} KB)");
        return 0;
    }

    public static JsonSerializerSettings BuildJsonSettings(IFileProvider provider)
    {
        var settings = new JsonSerializerSettings
        {
            Formatting = Formatting.Indented,
            NullValueHandling = NullValueHandling.Ignore,
            ReferenceLoopHandling = ReferenceLoopHandling.Ignore,
            MaxDepth = 32,
        };

        // CUE4Parse exposes JSON converters that know how to walk UObject graphs.
        var converterTypes = AllAsms().SelectMany(a =>
        {
            try { return a.GetExportedTypes(); }
            catch { return Array.Empty<Type>(); }
        })
            .Where(t => typeof(JsonConverter).IsAssignableFrom(t) && !t.IsAbstract)
            .ToList();
        foreach (var ct in converterTypes)
        {
            var ctor = ct.GetConstructors()
                .OrderBy(c => c.GetParameters().Length)
                .FirstOrDefault(c => c.GetParameters().All(p =>
                    p.ParameterType.IsAssignableFrom(provider.GetType())
                    || p.ParameterType == typeof(IFileProvider)
                    || p.HasDefaultValue));
            if (ctor is null) continue;
            var args = ctor.GetParameters().Select(p =>
            {
                if (p.ParameterType.IsInstanceOfType(provider)) return (object)provider;
                if (p.ParameterType == typeof(IFileProvider)) return provider;
                return p.HasDefaultValue ? p.DefaultValue : null;
            }).ToArray();
            try { settings.Converters.Add((JsonConverter)Activator.CreateInstance(ct, args)); }
            catch { /* converter needs something we don't have */ }
        }
        Console.Error.WriteLine($"[atlas] JSON converters: {string.Join(", ", settings.Converters.Select(c => c.GetType().Name))}");
        return settings;
    }

    private static string P(ParameterInfo p) =>
        $"{S(p.ParameterType)} {p.Name}{(p.HasDefaultValue ? " = " + (p.DefaultValue ?? "null") : "")}";

    private static string S(Type t)
    {
        if (t.IsByRef) return "ref " + S(t.GetElementType());
        if (t.IsArray) return S(t.GetElementType()) + "[]";
        if (t.IsGenericType) return t.Name.Split('`')[0] + "<" + string.Join(", ", t.GetGenericArguments().Select(S)) + ">";
        return t.Name;
    }
}
