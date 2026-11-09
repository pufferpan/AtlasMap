using CUE4Parse.FileProvider;

namespace Dfmap;

/// <summary>
/// Renders a top-down plan view of a merged scene.
///
/// Maps like SafeHouse (SafeHouse) ship no pre-baked overhead image, so the only way to get a
/// usable map picture is to draw the placed instances ourselves. Each instance is drawn as
/// the XY footprint of its mesh bounds (scaled), or as a fixed marker when the mesh could
/// not be decoded; colour encodes height so floors read apart.
/// </summary>
public static class PlanView
{
    public sealed class Item
    {
        public float X, Y, Z;
        public float FootprintX = 200f;   // UE cm
        public float FootprintY = 200f;
        public bool BoundsKnown;
    }

    public static void Render(string path, IReadOnlyList<Item> items, int maxPixels = 2048, string title = null)
    {
        if (items.Count == 0) { Console.Error.WriteLine("[plan] nothing to draw"); return; }

        // Robust framing: a handful of stray instances (a quest marker, a sky prop) would
        // otherwise blow the extent up and leave the actual map as a speck in one corner.
        const double P = 0.004;
        var sortedX = items.Select(i => i.X).OrderBy(v => v).ToArray();
        var sortedY = items.Select(i => i.Y).OrderBy(v => v).ToArray();
        var lo = (int)(sortedX.Length * P);
        var hi = Math.Min(sortedX.Length - 1, (int)(sortedX.Length * (1 - P)));
        float minX = sortedX[lo], maxX = sortedX[hi];
        float minY = sortedY[lo], maxY = sortedY[hi];
        float minZ = float.MaxValue, maxZ = float.MinValue;
        var clipped = 0;
        foreach (var it in items)
        {
            minZ = Math.Min(minZ, it.Z); maxZ = Math.Max(maxZ, it.Z);
            if (it.X < minX || it.X > maxX || it.Y < minY || it.Y > maxY) clipped++;
        }

        // pad so nothing sits on the border
        var padX = Math.Max(200f, (maxX - minX) * 0.02f);
        var padY = Math.Max(200f, (maxY - minY) * 0.02f);
        minX -= padX; maxX += padX; minY -= padY; maxY += padY;

        var spanX = Math.Max(maxX - minX, 1f);
        var spanY = Math.Max(maxY - minY, 1f);
        var scale = Math.Min(maxPixels / spanX, maxPixels / spanY);
        var w = Math.Max(64, (int)(spanX * scale));
        var h = Math.Max(64, (int)(spanY * scale));
        if ((long)w * h > 64_000_000) throw new InvalidOperationException($"plan too large: {w}x{h}");

        var px = new byte[w * h * 4];
        // background
        for (var i = 0; i < px.Length; i += 4)
        {
            px[i] = 18; px[i + 1] = 20; px[i + 2] = 24; px[i + 3] = 255;
        }

        // 64 m grid
        var gridStep = 6400f;
        for (var gx = MathF.Ceiling(minX / gridStep) * gridStep; gx <= maxX; gx += gridStep)
        {
            var x = (int)((gx - minX) * scale);
            if (x < 0 || x >= w) continue;
            for (var y = 0; y < h; y++) SetPx(px, w, x, y, 40, 44, 52, 255);
        }
        for (var gy = MathF.Ceiling(minY / gridStep) * gridStep; gy <= maxY; gy += gridStep)
        {
            var y = (int)((maxY - gy) * scale);
            if (y < 0 || y >= h) continue;
            for (var x = 0; x < w; x++) SetPx(px, w, x, y, 40, 44, 52, 255);
        }

        var zSpan = Math.Max(maxZ - minZ, 1f);
        // robust colour range: a single far-below outlier would otherwise wash the whole ramp out
        var zs = items.Select(i => i.Z).OrderBy(v => v).ToArray();
        var zLo = zs[(int)(zs.Length * 0.02)];
        var zHi = zs[Math.Min(zs.Length - 1, (int)(zs.Length * 0.98))];
        var zColorSpan = Math.Max(zHi - zLo, 1f);

        // draw large footprints first so small props stay visible on top
        foreach (var it in items.OrderByDescending(i => i.FootprintX * i.FootprintY))
        {
            var t = (it.Z - zLo) / zColorSpan;
            var (r, g, b) = HeightColor(t);
            var cx = (it.X - minX) * scale;
            var cy = (maxY - it.Y) * scale;
            var hw = Math.Max(1f, it.FootprintX * 0.5f * scale);
            var hh = Math.Max(1f, it.FootprintY * 0.5f * scale);
            var x0 = (int)(cx - hw); var x1 = (int)(cx + hw);
            var y0 = (int)(cy - hh); var y1 = (int)(cy + hh);
            for (var y = Math.Max(0, y0); y <= Math.Min(h - 1, y1); y++)
                for (var x = Math.Max(0, x0); x <= Math.Min(w - 1, x1); x++)
                    SetPx(px, w, x, y, r, g, b, it.BoundsKnown ? (byte)230 : (byte)130);
        }

        MapImage.WritePng(path, px, w, h);
        Console.WriteLine($"[plan] {items.Count} instances -> {path}  ({w}x{h}, " +
                          $"world {spanX / 100:0} m x {spanY / 100:0} m, " +
                          $"scale {scale * 100:0.0} px/m, Z {minZ / 100:0.#}..{maxZ / 100:0.#} m, " +
                          $"colour ramp over {zLo / 100:0.#}..{zHi / 100:0.#} m, " +
                          $"{clipped} instance(s) outside the framed extent)");
    }

    private static (byte, byte, byte) HeightColor(float t)
    {
        t = Math.Clamp(t, 0f, 1f);
        // blue (low) -> cyan -> green -> yellow -> red (high)
        var stops = new (float P, byte R, byte G, byte B)[]
        {
            (0.00f, 60, 110, 220), (0.25f, 60, 200, 200), (0.50f, 90, 210, 90),
            (0.75f, 230, 210, 70), (1.00f, 225, 80, 70),
        };
        for (var i = 1; i < stops.Length; i++)
        {
            if (t > stops[i].P) continue;
            var a = stops[i - 1];
            var b = stops[i];
            var k = (t - a.P) / Math.Max(b.P - a.P, 1e-6f);
            return ((byte)(a.R + (b.R - a.R) * k), (byte)(a.G + (b.G - a.G) * k), (byte)(a.B + (b.B - a.B) * k));
        }
        var l = stops[^1];
        return (l.R, l.G, l.B);
    }

    private static void SetPx(byte[] px, int w, int x, int y, byte r, byte g, byte b, byte a)
    {
        var o = (y * w + x) * 4;
        if (a == 255)
        {
            px[o] = r; px[o + 1] = g; px[o + 2] = b; px[o + 3] = 255;
            return;
        }
        // simple alpha blend over what is already there
        var k = a / 255f;
        px[o] = (byte)(px[o] * (1 - k) + r * k);
        px[o + 1] = (byte)(px[o + 1] * (1 - k) + g * k);
        px[o + 2] = (byte)(px[o + 2] * (1 - k) + b * k);
        px[o + 3] = 255;
    }
}
