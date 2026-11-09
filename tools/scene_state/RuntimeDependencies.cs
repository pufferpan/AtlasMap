using System.Reflection;
using System.Runtime.Loader;

// Native workers may be launched from a temporary single-file extraction.
// Resolve from both complete payloads, and load the lazily used codec before
// opening any map: otherwise the first failure can occur in PakFileReader.Dispose.
internal static class RuntimeDependencies {
    internal static void Install(string reference) {
        var directories = new[] { Path.GetFullPath(reference), AppContext.BaseDirectory };
        AssemblyLoadContext.Default.Resolving += (context, name) => {
            foreach (var directory in directories) {
                var path = Path.Combine(directory, name.Name + ".dll");
                if (!File.Exists(path)) continue;
                var identity = AssemblyName.GetAssemblyName(path);
                if (identity.Name != name.Name || (name.Version is not null && identity.Version < name.Version)) continue;
                return context.LoadFromAssemblyPath(path);
            }
            return null;
        };
        var codec = AssemblyLoadContext.Default.LoadFromAssemblyName(new AssemblyName(
            "ZstdSharp, Version=0.8.8.0, Culture=neutral, PublicKeyToken=8d151af33a4ad5cf"));
        if (codec.GetType("ZstdSharp.Decompressor", true) is null)
            throw new InvalidDataException("ZstdSharp 解压依赖不完整，请重新解压完整程序包。");
        Console.WriteLine($"[runtime] ZstdSharp {codec.GetName().Version} ready");
    }
}
