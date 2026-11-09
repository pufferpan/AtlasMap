using System.IO.Compression;
using System.Text.RegularExpressions;
using CUE4Parse_Conversion.Textures;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Texture;
using Newtonsoft.Json;

namespace Dfmap;

/// <summary>
/// Exports a map's in-game overhead image (the "clipmap") straight from the paks.
///
/// The game ships it pre-tiled: Content/BluePrints/Map/Textures/&lt;Map&gt;/&lt;ClipMap&gt;/
/// Mip{m}_y{y}_x{x}.uasset, e.g. 8x8 tiles of 512px (4096^2) or 16x16 (8192^2), each with
/// its own mip chain. Stitching them gives the full map picture.
/// </summary>
public static class MapImage
{
    private static readonly Regex TileRe = new(@"^Mip(?<m>\d+)_y(?<y>\d+)_x(?<x>\d+)$", RegexOptions.IgnoreCase);
    private const string TexRoot = "DeltaForce/Content/BluePrints/Map/Textures/";

    public sealed class TileInfo
    {
        public int Mip { get; set; }
        public int X { get; set; }
        public int Y { get; set; }
        public string Package { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public string PixelFormat { get; set; }
        public string Error { get; set; }
    }

    public static int CmdMap(IFileProvider provider, string[] args)
    {
        if (args.Length == 0)
        {
            Console.Error.WriteLine("usage: dfmap map <mapName|all> <outDir> [--mip N] [--swap-rb] [--list]");
            Console.Error.WriteLine("  e.g. dfmap map AZ-5 G:\\out\\maps");
            return 2;
        }
        var which = args[0];
        var outDir = args.Length > 1 && !args[1].StartsWith("--") ? args[1] : ".";
        var onlyMip = GetOpt(args, "--mip") is { } m ? int.Parse(m) : (int?)null;
        var swapRb = args.Contains("--swap-rb");
        var listOnly = args.Contains("--list");
        Directory.CreateDirectory(outDir);

        // ---- discover clipmap folders ----
        var folders = provider.Files.Keys
            .Where(p => p.StartsWith(TexRoot, StringComparison.OrdinalIgnoreCase)
                        && p.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
            .GroupBy(p => Path.GetDirectoryName(p).Replace('\\', '/') + "/", StringComparer.OrdinalIgnoreCase)
            .Select(g => new
            {
                Folder = g.Key,
                Tiles = g.Select(p => (Path: p, M: TileRe.Match(Path.GetFileNameWithoutExtension(p))))
                         .Where(t => t.M.Success).ToList(),
            })
            .Where(g => g.Tiles.Count > 0)
            .OrderBy(g => g.Folder, StringComparer.OrdinalIgnoreCase)
            .ToList();

        Console.WriteLine($"clipmap folders found: {folders.Count}");
        if (listOnly)
        {
            foreach (var f in folders)
                Console.WriteLine($"  {f.Tiles.Count,5} tiles   {f.Folder.Replace(TexRoot, "")}");
            return 0;
        }

        var selection = which.Equals("all", StringComparison.OrdinalIgnoreCase)
            ? folders
            : folders.Where(f => f.Folder.Contains("/" + which + "/", StringComparison.OrdinalIgnoreCase)).ToList();
        if (selection.Count == 0)
        {
            Console.Error.WriteLine($"no clipmap folder matches '{which}'. Use --list to see what exists.");
            return 1;
        }

        var report = new List<object>();
        foreach (var f in selection)
        {
            var rel = f.Folder.Replace(TexRoot, "").TrimEnd('/');
            Console.WriteLine($"\n=== {rel}  ({f.Tiles.Count} tiles) ===");
            ProcessFolder(provider, f.Folder, f.Tiles.Select(t => (t.Path, t.M)).ToList(),
                          outDir, rel, onlyMip, swapRb, report);
        }

        var reportPath = Path.Combine(outDir, "map_export_report.json");
        File.WriteAllText(reportPath, JsonConvert.SerializeObject(report, Formatting.Indented));
        Console.WriteLine($"\nwrote {reportPath}");
        return 0;
    }

    private static void ProcessFolder(IFileProvider provider, string folder,
                                      List<(string Path, Match M)> tiles, string outDir, string rel,
                                      int? onlyMip, bool swapRb, List<object> report)
    {
        var mips = tiles.Select(t => int.Parse(t.M.Groups["m"].Value)).Distinct().OrderBy(x => x).ToList();
        foreach (var mip in mips)
        {
            if (onlyMip is not null && mip != onlyMip) continue;
            var cells = tiles.Where(t => int.Parse(t.M.Groups["m"].Value) == mip).ToList();
            var xs = cells.Select(t => int.Parse(t.M.Groups["x"].Value)).Distinct().OrderBy(v => v).ToList();
            var ys = cells.Select(t => int.Parse(t.M.Groups["y"].Value)).Distinct().OrderBy(v => v).ToList();
            Console.WriteLine($"  Mip{mip}: {xs.Count} x {ys.Count} tiles");

            // decode every tile, remember the tile size
            var decoded = new Dictionary<(int X, int Y), byte[]>();
            int tw = 0, th = 0, failures = 0;
            string fmt = null;
            foreach (var (path, m) in cells)
            {
                var x = int.Parse(m.Groups["x"].Value);
                var y = int.Parse(m.Groups["y"].Value);
                try
                {
                    var (pkg, obj) = MeshCache.SplitObjectPath(path);
                    var tex = provider.LoadPackageObject<UTexture2D>(pkg, obj);
                    if (tex is null) { failures++; continue; }
                    var ctex = tex.Decode(ETexturePlatform.DesktopMobile);
                    if (ctex is null) { failures++; continue; }
                    tw = ctex.Width; th = ctex.Height; fmt = ctex.PixelFormat.ToString();
                    decoded[(x, y)] = swapRb ? SwapRb(ctex.Data) : ctex.Data;
                }
                catch (Exception ex)
                {
                    failures++;
                    if (failures <= 3) Console.WriteLine($"    tile y{y}_x{x}: {ex.GetType().Name}: {ex.Message}");
                }
            }
            if (decoded.Count == 0) { Console.WriteLine("    no tiles decoded"); continue; }

            var width = xs.Count * tw;
            var height = ys.Count * th;
            Console.WriteLine($"    decoded {decoded.Count}/{cells.Count} tiles  {tw}x{th} each  -> {width}x{height}  format={fmt}");
            if (failures > 0) Console.WriteLine($"    !! {failures} tiles failed");

            var canvas = new byte[(long)width * height * 4];
            foreach (var ((x, y), data) in decoded)
            {
                var ox = xs.IndexOf(x) * tw;
                var oy = ys.IndexOf(y) * th;
                for (var row = 0; row < th && row < Math.Min(th, data.Length / Math.Max(1, tw * 4)); row++)
                {
                    var srcStart = row * tw * 4;
                    if (srcStart + tw * 4 > data.Length) break;
                    var dstStart = (long)(oy + row) * width * 4 + ox * 4;
                    Array.Copy(data, srcStart, canvas, dstStart, tw * 4);
                }
            }

            var name = $"{rel.Replace('/', '_')}_Mip{mip}.png";
            var outPath = Path.Combine(outDir, name);
            WritePng(outPath, canvas, width, height);
            var mb = new FileInfo(outPath).Length / 1024.0 / 1024.0;
            Console.WriteLine($"    wrote {name}  ({mb:0.00} MB)");

            report.Add(new
            {
                map = rel,
                mip,
                gridX = xs.Count,
                gridY = ys.Count,
                tileWidth = tw,
                tileHeight = th,
                width,
                height,
                tilesDecoded = decoded.Count,
                tilesFailed = failures,
                pixelFormat = fmt,
                file = name,
                bytes = new FileInfo(outPath).Length,
            });

            // small preview for quick eyeballing
            if (mip == mips.Min())
            {
                var pv = Downsample(canvas, width, height, 1024);
                var pvPath = Path.Combine(outDir, $"{rel.Replace('/', '_')}_Mip{mip}_preview.png");
                WritePng(pvPath, pv, Math.Min(width, 1024), Math.Min(height, 1024));
                Console.WriteLine($"    wrote {Path.GetFileName(pvPath)}");
            }
        }
    }

    private static byte[] SwapRb(byte[] src)
    {
        var dst = (byte[])src.Clone();
        for (var i = 0; i + 3 < dst.Length; i += 4) (dst[i], dst[i + 2]) = (dst[i + 2], dst[i]);
        return dst;
    }

    private static byte[] Downsample(byte[] src, int w, int h, int max)
    {
        if (w <= max && h <= max) return src;
        var scale = Math.Max(1, Math.Max(w, h) / max);
        var nw = w / scale;
        var nh = h / scale;
        var dst = new byte[nw * nh * 4];
        for (var y = 0; y < nh; y++)
            for (var x = 0; x < nw; x++)
                for (var c = 0; c < 4; c++)
                    dst[(y * nw + x) * 4 + c] = src[((long)y * scale * w + (long)x * scale) * 4 + c];
        return dst;
    }

    // ---------------------------------------------------------------- minimal PNG writer

    private static readonly uint[] CrcTable = BuildCrcTable();

    private static uint[] BuildCrcTable()
    {
        var t = new uint[256];
        for (uint n = 0; n < 256; n++)
        {
            var c = n;
            for (var k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            t[n] = c;
        }
        return t;
    }

    private static uint Crc32(byte[] buf, int offset, int count)
    {
        var c = 0xFFFFFFFFu;
        for (var i = offset; i < offset + count; i++) c = CrcTable[(c ^ buf[i]) & 0xFF] ^ (c >> 8);
        return c ^ 0xFFFFFFFFu;
    }

    private static void WriteChunk(Stream s, string type, byte[] data)
    {
        var len = BitConverter.GetBytes(data.Length);
        Array.Reverse(len);
        s.Write(len);
        var typeBytes = System.Text.Encoding.ASCII.GetBytes(type);
        s.Write(typeBytes);
        s.Write(data);
        var crcInput = new byte[typeBytes.Length + data.Length];
        Buffer.BlockCopy(typeBytes, 0, crcInput, 0, typeBytes.Length);
        Buffer.BlockCopy(data, 0, crcInput, typeBytes.Length, data.Length);
        var crc = BitConverter.GetBytes(Crc32(crcInput, 0, crcInput.Length));
        Array.Reverse(crc);
        s.Write(crc);
    }

    /// <summary>Zero-dependency RGBA8 PNG writer (only System.IO.Compression is used).</summary>
    public static void WritePng(string path, byte[] rgba, int width, int height)
    {
        using var fs = File.Create(path);
        fs.Write(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A });

        var ihdr = new byte[13];
        WriteBe(ihdr, 0, width);
        WriteBe(ihdr, 4, height);
        ihdr[8] = 8;    // bit depth
        ihdr[9] = 6;    // colour type: RGBA
        ihdr[10] = 0;   // deflate
        ihdr[11] = 0;   // adaptive filtering
        ihdr[12] = 0;   // no interlace
        WriteChunk(fs, "IHDR", ihdr);

        using var raw = new MemoryStream(width * height * 4 + height);
        var filter = new byte[1];
        for (var y = 0; y < height; y++)
        {
            raw.Write(filter);                                   // filter type 0 (None)
            raw.Write(rgba, y * width * 4, width * 4);
        }

        using var compressed = new MemoryStream();
        using (var z = new ZLibStream(compressed, CompressionLevel.Optimal, leaveOpen: true))
            raw.WriteTo(z);
        WriteChunk(fs, "IDAT", compressed.ToArray());
        WriteChunk(fs, "IEND", Array.Empty<byte>());
    }

    private static void WriteBe(byte[] buf, int offset, int value)
    {
        buf[offset] = (byte)(value >> 24);
        buf[offset + 1] = (byte)(value >> 16);
        buf[offset + 2] = (byte)(value >> 8);
        buf[offset + 3] = (byte)value;
    }

    private static string GetOpt(string[] args, string name)
    {
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
