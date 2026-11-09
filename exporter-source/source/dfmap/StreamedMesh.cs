using CUE4Parse.FileProvider;
using Newtonsoft.Json;

namespace Dfmap;

/// <summary>
/// Self-contained decoder for Game's streamed static-mesh LODs.
///
/// CUE4Parse's own reader throws in FDeltaForceStaticMeshRenderData.SkipDistanceFields for
/// this game build (see README §6.1), so we read the blobs ourselves. The layout was
/// reverse-engineered and is verified by construction rather than by trusting an offset:
///
///   .uexp  : an FByteBulkData header {flags:u32, elementCount:i32, sizeOnDisk:i32,
///            offsetInFile:i64} whose payload dominates the package's .ubulk
///   .ubulk : 2-byte strip flags, then (stride, count) twice, then the vertex data.
/// Index arrays carry their own serialized byte count. Range/degeneracy checks
/// alone cannot distinguish topology from adjacent auxiliary index buffers.
/// </summary>
public static class StreamedMesh
{
    public sealed class Stats
    {
        public int Attempted, Decoded, NoPayload, NoHeader, NoIndices;
        public readonly List<string> Failures = new();
        public readonly List<string> Trace = new();
    }

    public static bool Verbose;

    /// <summary>
    /// Allow the triangle-strip fallback, which synthesises triangles from vertex order when a
    /// mesh has no index buffer at all.
    ///
    /// OFF by default. It is a guess by construction: applied to a mesh that is not actually a
    /// strip it produces geometry that references the right vertices in the wrong order, so the
    /// prop arrives deformed rather than missing. A deformed prop makes the whole export look
    /// broken, which is much worse than an absent one, so this stays opt-in until it can be told
    /// apart from a real strip by evidence rather than by hope. ATLASMAP_STRIPS=1 turns it on.
    /// </summary>
    public static bool AllowStrips = Environment.GetEnvironmentVariable("ATLASMAP_STRIPS") == "1";

    /// <summary>
    /// Allow the index scan to accept a run that leaves up to three trailing vertices
    /// unreferenced. OFF by default: it widens what counts as a hit, and a wrong run that happens
    /// to reference valid vertices produces large, non-degenerate triangles - so it sails past
    /// the degeneracy check and the ExtendedBounds check alike, and arrives as a deformed prop
    /// rather than a missing one. ATLASMAP_RELAXED=1 turns it on.
    /// </summary>
    public static bool AllowRelaxedIndices = Environment.GetEnvironmentVariable("ATLASMAP_RELAXED") == "1";

    /// <summary>
    /// Allow a second scan pass treating the buffer as uint32 indices. OFF by default for the
    /// same reason as AllowRelaxedIndices. ATLASMAP_U32=1 turns it on.
    /// </summary>
    public static bool AllowU32Indices = Environment.GetEnvironmentVariable("ATLASMAP_U32") == "1";

    private const int MaxVertexStrides = 64;

    /// <summary>Decode a streamed mesh straight from its .uexp/.ubulk pair. Null when not applicable.</summary>
    /// <param name="expMin">Declared local bounds minimum (cm), or null when the asset has none.</param>
    /// <param name="expMax">Declared local bounds maximum (cm), or null when the asset has none.</param>
    public static MeshData Decode(IFileProvider provider, string meshObjectPath, Stats stats = null,
                                  float[] expMin = null, float[] expMax = null)
    {
        stats ??= new Stats();
        stats.Attempted++;

        var (pkgPath, _) = MeshCache.SplitObjectPath(meshObjectPath);
        if (!provider.TryGetGameFile(pkgPath + ".uexp", out var uexpFile))
        {
            stats.NoPayload++;
            return null;
        }

        byte[] uexp, ubulk;
        try
        {
            uexp = uexpFile.Read();
            // Small procedural meshes and Iceland's water planes store their
            // complete serialized render buffers inline, without a .ubulk.
            ubulk = provider.TryGetGameFile(pkgPath + ".ubulk", out var ubulkFile)
                ? ubulkFile.Read() : uexp;
        }
        catch (Exception ex)
        {
            stats.Failures.Add($"{meshObjectPath}: read {ex.GetType().Name}");
            return null;
        }

        // Pick LOD0 before looking for indices. Do not fall through to a lower
        // LOD when its index buffer happens to be easier to decode.
        var blocks = SelfDescribingBlocks(ubulk)
            .Where(b => BitConverter.ToInt32(ubulk, b.Offset + 2) == 12
                        && PositionBlockFits(ubulk, b.Offset, b.Size, expMin, expMax))
            .OrderByDescending(b => BitConverter.ToInt32(ubulk, b.Offset + 6))
            .ToList();
        if (blocks.Count > 0)
        {
            var chosen = blocks[0];
            var md = TryLayout(ubulk, chosen.Offset, chosen.Size, meshObjectPath, 18, 18, expMin, expMax);
            if (md is not null) { stats.Decoded++; return md; }
            stats.NoIndices++;
            stats.Failures.Add($"{meshObjectPath}: LOD0 serialized index buffer not found");
            return null;
        }

        var seen = new HashSet<int>();
        foreach (var (off, size, elem) in BulkRefs(uexp, ubulk.Length))
        {
            if (!seen.Add(off)) continue;
            var md = DecodeBlob(ubulk, off, size, meshObjectPath, stats, expMin, expMax);
            if (md is null) continue;
            stats.Decoded++;
            return md;
        }

        stats.NoHeader++;
        if (stats.Failures.Count < 25) stats.Failures.Add($"{meshObjectPath}: no decodable blob");
        return null;
    }

    private static bool PositionBlockFits(byte[] data, int offset, int size, float[] expMin, float[] expMax)
    {
        var count = BitConverter.ToInt32(data, offset + 6);
        if (18L + count * 12L > size) return false;
        var min = new[] { float.MaxValue, float.MaxValue, float.MaxValue };
        var max = new[] { float.MinValue, float.MinValue, float.MinValue };
        for (var i = 0; i < count; i++)
            for (var axis = 0; axis < 3; axis++)
            {
                var value = BitConverter.ToSingle(data, offset + 18 + i * 12 + axis * 4);
                if (!float.IsFinite(value) || MathF.Abs(value) > 1e7f) return false;
                min[axis] = MathF.Min(min[axis], value);
                max[axis] = MathF.Max(max[axis], value);
            }
        return Fits(min, max, expMin, expMax);
    }

    /// <summary>
    /// True when a decode fits the bounds the mesh asset declares, with a little slack for
    /// float noise. This is the strongest available check on a reverse-engineered layout: the
    /// declared box comes from the asset itself, not from the bytes being interpreted.
    /// </summary>
    private static bool Fits(float[] min, float[] max, float[] expMin, float[] expMax)
    {
        if (expMin is null || expMax is null) return true;
        for (var a = 0; a < 3; a++)
        {
            var slack = MathF.Max(1.0f, (expMax[a] - expMin[a]) * 0.02f);
            if (min[a] < expMin[a] - slack) return false;
            if (max[a] > expMax[a] + slack) return false;
        }
        return true;
    }

    /// <summary>
    /// Every offset in the .ubulk that starts a self-describing LOD block. The block extends to
    /// the next such offset, or to the end of the payload for the last one.
    /// </summary>
    private static IEnumerable<(int Offset, int Size)> SelfDescribingBlocks(byte[] ubulk)
    {
        var starts = new List<int>();
        // Inline export properties can end at an odd byte offset (the Iceland
        // water-plane position buffer starts at 1397), so scan every byte.
        for (var o = 0; o + 18 <= ubulk.Length && starts.Count < 64; o++)
        {
            var s1 = BitConverter.ToInt32(ubulk, o + 2);
            var c1 = BitConverter.ToInt32(ubulk, o + 6);
            var s2 = BitConverter.ToInt32(ubulk, o + 10);
            var c2 = BitConverter.ToInt32(ubulk, o + 14);
            if (s1 != s2 || c1 != c2) continue;
            // Position buffers contain FVector (12-byte) entries. UV/tangent
            // buffers must not truncate the LOD's search interval.
            if (s1 != 12) continue;
            if (c1 < 3 || c1 > 4_000_000) continue;
            if ((long)o + 18 + (long)c1 * s1 > ubulk.Length) continue;
            starts.Add(o);
        }
        for (var i = 0; i < starts.Count; i++)
        {
            var end = i + 1 < starts.Count ? starts[i + 1] : ubulk.Length;
            if (end - starts[i] < 64) continue;
            yield return (starts[i], end - starts[i]);
        }
    }

    /// <summary>Candidate FByteBulkData references whose payload dominates the .ubulk.</summary>
    private static IEnumerable<(int Offset, int Size, int Elements)> BulkRefs(byte[] uexp, int ubulkLength)
    {
        for (var o = 0; o + 20 <= uexp.Length; o++)
        {
            var flags = BitConverter.ToUInt32(uexp, o);
            if (flags == 0 || flags > 0x0FFFFFFF) continue;
            var elem = BitConverter.ToInt32(uexp, o + 4);
            var size = BitConverter.ToInt32(uexp, o + 8);
            var off = BitConverter.ToInt64(uexp, o + 12);
            if (elem <= 0 || size <= 4096 || off < 0 || off + size > ubulkLength) continue;
            if (size < ubulkLength / 2) continue;
            if (Verbose) Console.Error.WriteLine($"[blob] ref @uexp{o} flags=0x{flags:X8} elem={elem} size={size} off={off}");
            yield return ((int)off, size, elem);
        }
    }

    /// <summary>
    /// Triangle list for a mesh with no index buffer, drawn as a strip in vertex order.
    ///
    /// A strip of n vertices is n-2 triangles, alternating winding so the faces stay consistent:
    /// (0,1,2), (2,1,3), (2,3,4), (4,3,5) ... The result is still checked against the same
    /// degeneracy rule as a decoded index buffer, so a mesh that is not actually a strip comes
    /// out degenerate and is rejected rather than imported as a tangle.
    /// </summary>
    private static uint[] StripIndices(int vertexCount, float[] positions)
    {
        if (vertexCount < 3) return null;
        var indices = new uint[(vertexCount - 2) * 3];
        var k = 0;
        for (var i = 0; i + 2 < vertexCount; i++)
        {
            if ((i & 1) == 0) { indices[k++] = (uint)i; indices[k++] = (uint)(i + 1); indices[k++] = (uint)(i + 2); }
            else { indices[k++] = (uint)(i + 1); indices[k++] = (uint)i; indices[k++] = (uint)(i + 2); }
        }
        return DegenerateFraction(positions, indices) <= 0.05 ? indices : null;
    }

    private static MeshData DecodeBlob(byte[] ubulk, int offset, int size, string meshPath, Stats stats,
                                       float[] expMin = null, float[] expMax = null)
    {
        // The vertex block header is a doubled (stride, count) pair after 2 strip-flag bytes,
        // but a few assets use a single pair or put the pair elsewhere; try the variants and
        // let the index self-check decide which one is real.
        foreach (var (headerLen, dataStart) in new[] { (18, 18), (10, 10), (16, 16) })
        {
            var md = TryLayout(ubulk, offset, size, meshPath, headerLen, dataStart, expMin, expMax);
            if (md is not null) return md;
        }
        if (Verbose) Console.Error.WriteLine($"[blob] no layout matched (size={size})");
        return null;
    }

    private static MeshData TryLayout(byte[] ubulk, int offset, int size, string meshPath,
                                      int headerLen, int dataStart,
                                      float[] expMin = null, float[] expMax = null)
    {
        if (size < headerLen + 12) return null;
        var stride = headerLen == 10 ? 12 : 12;
        int count;

        if (headerLen == 18)
        {
            var s1 = BitConverter.ToInt32(ubulk, offset + 2);
            var c1 = BitConverter.ToInt32(ubulk, offset + 6);
            var s2 = BitConverter.ToInt32(ubulk, offset + 10);
            var c2 = BitConverter.ToInt32(ubulk, offset + 14);
            if (s1 != s2 || c1 != c2) return null;
            stride = s1; count = c1;
        }
        else if (headerLen == 10)
        {
            stride = BitConverter.ToInt32(ubulk, offset + 2);
            count = BitConverter.ToInt32(ubulk, offset + 6);
        }
        else
        {
            stride = BitConverter.ToInt32(ubulk, offset);
            count = BitConverter.ToInt32(ubulk, offset + 8);
        }

        if (stride < 8 || stride > MaxVertexStrides || stride % 4 != 0) return null;
        if (count < 3 || (long)count * stride > size) return null;

        var pos = new float[count * 3];
        for (var i = 0; i < count; i++)
        {
            var p = offset + dataStart + i * stride;
            if (p + 12 > offset + size) return null;
            pos[i * 3] = BitConverter.ToSingle(ubulk, p);
            pos[i * 3 + 1] = BitConverter.ToSingle(ubulk, p + 4);
            pos[i * 3 + 2] = BitConverter.ToSingle(ubulk, p + 8);
        }
        for (var i = 0; i < pos.Length; i++)
            if (float.IsNaN(pos[i]) || MathF.Abs(pos[i]) > 1e7) return null;

        // Strict first, relaxed only as a fallback. Relaxing acceptance directly (allowing a
        // short vertex-count shortfall, or synthesising a strip) turned "mesh missing" into
        // "mesh deformed", which is far worse: a missing prop is obvious, a scrambled one looks
        // like the export is broken. So the original, reliable test runs to completion first and
        // the looser encodings are only consulted when it finds nothing at all.
        var indices = FindSerializedIndices(ubulk, offset, size, dataStart + count * stride, count, pos);
        // The old run scanner can join the main, reversed, depth-only and
        // wireframe arrays. Keep it strictly opt-in for historical diagnostics.
        if (indices is null && Environment.GetEnvironmentVariable("ATLASMAP_LEGACY_INDICES") == "1")
            indices = FindIndices(ubulk, offset, size, dataStart + count * stride, count, pos, 2, true);
        if (indices is null && AllowRelaxedIndices)
            indices = FindIndices(ubulk, offset, size, dataStart + count * stride, count, pos, 2, false);
        if (indices is null && AllowU32Indices)
        {
            indices = FindIndices(ubulk, offset, size, dataStart + count * stride, count, pos, 4, true);
            if (indices is not null && Verbose)
                Console.Error.WriteLine($"[blob] header {headerLen}: uint32 index buffer");
        }
        if (indices is null && AllowStrips)
        {
            // ...and meshes with no index buffer at all, drawn as a triangle strip in vertex
            // order. A strip of n vertices is n-2 triangles, which fits these props exactly.
            indices = StripIndices(count, pos);
            if (indices is not null && Verbose)
                Console.Error.WriteLine($"[blob] header {headerLen}: triangle strip, no index buffer");
        }
        if (indices is null)
        {
            if (Verbose) Console.Error.WriteLine($"[blob] header {headerLen}: no self-validating indices (count={count}, stride={stride})");
            return null;
        }

        var min = new[] { float.MaxValue, float.MaxValue, float.MaxValue };
        var max = new[] { float.MinValue, float.MinValue, float.MinValue };
        for (var i = 0; i < count; i++)
            for (var a = 0; a < 3; a++)
            {
                var c = pos[i * 3 + a];
                if (c < min[a]) min[a] = c;
                if (c > max[a]) max[a] = c;
            }

        if (!Fits(min, max, expMin, expMax))
        {
            if (Verbose)
                Console.Error.WriteLine($"[blob] header {headerLen} rejected: decodes outside declared bounds " +
                                        $"({min[0]:0.#},{min[1]:0.#},{min[2]:0.#})..({max[0]:0.#},{max[1]:0.#},{max[2]:0.#})");
            return null;
        }

        if (Verbose)
            Console.Error.WriteLine($"[blob] OK header={headerLen} stride={stride} verts={count} tris={indices.Length / 3}");

        var uvs = new float[count * 2];
        float[][] uvChannels = null;
        byte[] colors = null;
        var colorState = "unavailable";
        var normals = SmoothNormals(pos, indices);
        try
        {
            using var archive = new CUE4Parse.UE4.Readers.FByteArchive(meshPath, ubulk,
                new CUE4Parse.UE4.Versions.VersionContainer(CUE4Parse.UE4.Versions.EGame.GAME_DeltaForce));
            archive.Position = offset + dataStart + count * stride;
            var buffer = new CUE4Parse.UE4.Assets.Exports.StaticMesh.FStaticMeshVertexBuffer(archive);
            if (buffer.NumVertices == count && buffer.UV?.Length == count && buffer.NumTexCoords > 0)
            {
                uvChannels = Enumerable.Range(0, buffer.NumTexCoords).Select(_ => new float[count * 2]).ToArray();
                for (var i = 0; i < count; i++)
                {
                    var item = buffer.UV[i];
                    if (item.UV is { Length: > 0 })
                    {
                        var uv = item.UV[0];
                        if (float.IsFinite(uv.U) && float.IsFinite(uv.V))
                        { uvs[i*2] = uv.U; uvs[i*2+1] = uv.V; }
                        for (var channel = 0; channel < item.UV.Length && channel < uvChannels.Length; channel++)
                        {
                            var sample = item.UV[channel];
                            if (!float.IsFinite(sample.U) || !float.IsFinite(sample.V))
                                throw new InvalidDataException("Non-finite authored UV");
                            uvChannels[channel][i*2] = sample.U;
                            uvChannels[channel][i*2+1] = sample.V;
                        }
                    }
                    // UE stores tangent X at 0 and tangent Z (the surface normal)
                    // at 2; entry 1 is reconstructed, not the surface normal.
                    if (item.Normal is { Length: > 2 })
                    { normals[i*3] = item.Normal[2].X; normals[i*3+1] = item.Normal[2].Y; normals[i*3+2] = item.Normal[2].Z; }
                }
            }
            try
            {
                var colorBuffer=new CUE4Parse.UE4.Objects.Meshes.FColorVertexBuffer(archive);
                if(colorBuffer.NumVertices==count && colorBuffer.Stride==4 && colorBuffer.Data?.Length==count)
                {
                    colors=colorBuffer.Data.SelectMany(c=>new[]{c.R,c.G,c.B,c.A}).ToArray();
                    colorState="authored";
                }
                else if(colorBuffer.NumVertices==0 && (colorBuffer.Data is null || colorBuffer.Data.Length==0))
                    colorState="default_white";
            }
            catch(Exception ex)
            { if(Verbose)Console.Error.WriteLine($"[blob] vertex colours unavailable: {ex.Message}"); }
        }
        catch (Exception ex)
        {
            if (Verbose) Console.Error.WriteLine($"[blob] vertex attributes unavailable: {ex.Message}");
        }
        return new MeshData
        {
            Path = meshPath,
            Positions = pos,
            Normals = normals,
            Uvs = uvs,
            UvChannels = uvChannels,
            Colors = colors,
            ColorBufferState = colorState,
            Indices = indices,
            SectionMaterial = Array.Empty<int>(),
            BoundsMin = min,
            BoundsMax = max,
        };
    }

    /// <summary>
    /// Read FRawStaticIndexBuffer's serialized byte array: bool Is32Bit,
    /// int ElementSize (=1), int ByteCount, then exactly ByteCount bytes.
    /// Verified against independently exported FModel UEMODEL LOD0 indices.
    /// The first valid array is the render index buffer; subsequent arrays can
    /// be reversed/depth/wireframe data and must not be concatenated with it.
    /// </summary>
    private static uint[] FindSerializedIndices(byte[] data, int offset, int size, int from,
                                                int vertexCount, float[] positions)
    {
        var limit = offset + size;
        for (var header = offset + from; header + 12 <= limit; header += 2)
        {
            var is32 = BitConverter.ToInt32(data, header);
            if (is32 is not (0 or 1) || BitConverter.ToInt32(data, header + 4) != 1) continue;
            var bytes = BitConverter.ToInt32(data, header + 8);
            var width = is32 == 1 ? 4 : 2;
            if (bytes < width * 3 || bytes % (width * 3) != 0 || (long)header + 12 + bytes > limit) continue;
            var n = bytes / width;
            if (n > 8_000_000) continue;
            var indices = new uint[n];
            uint max = 0;
            var valid = true;
            for (var i = 0; i < n; i++)
            {
                var value = width == 4 ? BitConverter.ToUInt32(data, header + 12 + i * 4)
                                      : BitConverter.ToUInt16(data, header + 12 + i * 2);
                if (value >= vertexCount) { valid = false; break; }
                indices[i] = value;
                max = Math.Max(max, value);
            }
            if (!valid || max != vertexCount - 1 || DegenerateFraction(positions, indices) > 0.05) continue;
            if (Verbose) Console.Error.WriteLine($"[blob] serialized indices @{header + 12}, width={width}, count={n}");
            return indices;
        }
        return null;
    }

    /// <summary>
    /// Locate the triangle list. `max(index) == vertexCount-1` narrows it down, but several
    /// 2-byte-shifted offsets satisfy that, and picking the wrong one scrambles the mesh
    /// (a 2-byte shift produced ~30% degenerate triangles versus 0.06% for the right one).
    /// So the winner is the candidate with the fewest degenerate triangles.
    /// </summary>
    private static uint[] FindIndices(byte[] ubulk, int blobOffset, int blobSize, int from,
                                      int vertexCount, float[] positions, int indexSize = 2,
                                      bool strict = true)
    {
        var limit = blobOffset + blobSize;
        uint[] best = null;
        var bestTris = 0;
        var bestDegen = double.MaxValue;
        // Scan the WHOLE blob. This used to stop 600,000 bytes past the vertex data, which is
        // arbitrary and silently wrong on big meshes: SM_BS_Military_Machines_SteelFrames_01 has a
        // 9,489,408-byte payload with its 71,947 vertices occupying only the first 863,382 of it,
        // so the index buffer sat far outside the window. The scan then settled for whatever
        // candidate it could find nearer the start - vertices right, connectivity wrong, which is
        // exactly what a deformed prop looks like. The run walk already bounds-checks every read
        // and skips whole runs, so covering the full range stays roughly linear.
        var scanEnd = limit;

        // The headroom guard used to be "o + 64 <= scanEnd", which never scanned the last 64 bytes
        // of a blob. Small props put their index buffer exactly there: SM_BS_Screen_Left_01 has a
        // 590-byte payload with its triangles starting at 530, so it was unreachable and the mesh
        // was thrown away despite the data being present and correct. Three bytes are all the
        // probe needs; the run walk below bounds-checks every read against `limit` anyway.
        for (var o = blobOffset + from; o + 3 <= scanEnd; o += 2)
        {
            // Do not require the run to start at index 0: plenty of cooked buffers begin on an
            // arbitrary vertex. Runs are cheap to reject, so the whole region is scanned.
            var max = 0;
            var n = 0;
            var p = o;
            while (p + indexSize <= limit && n < 8_000_000)
            {
                var v = indexSize == 4 ? BitConverter.ToUInt32(ubulk, p) : BitConverter.ToUInt16(ubulk, p);
                if (v >= (uint)vertexCount) break;
                if (v > max) max = (int)v;
                n++;
                p += indexSize;
            }
            // A floor of 30 indices (10 triangles) silently excluded every decal, screen, poster
            // and emissive plane in the map: those are quads and single triangles, so 6 or 3
            // indices. They are the simplest meshes in the scene, which is why the missing
            // objects were exactly the flat ones. The max(index) == vertexCount-1 test is what
            // actually validates a candidate, and it is just as decisive on a single triangle.
            if (n < 3) continue;
            // In strict mode the index buffer must reference the last vertex, which is the test
            // that has always been reliable. The relaxed mode allows a few trailing vertices to go
            // unreferenced, and is only reached when strict found nothing in the whole blob.
            var shortfall = strict ? 0 : 3;
            if (max < vertexCount - 1 - shortfall || max > vertexCount - 1)
            {
                if (n > 64) o = p - 4;                              // skip the run, keep the scan linear
                continue;
            }

            // Evaluate a few 2-byte shifts inside this run and keep the cleanest result; among
            // equally clean candidates the longest triangle list wins, because a short window
            // can be degenerate-free by accident.
            for (var shift = 0; shift <= (indexSize == 4 ? 4 : 6) && o + shift + indexSize <= p; shift += 2)
            {
                var usable = n - shift / indexSize;
                usable -= usable % 3;
                if (usable < 3) continue;
                var idx = new uint[usable];
                for (var i = 0; i < usable; i++)
                    idx[i] = indexSize == 4 ? BitConverter.ToUInt32(ubulk, o + shift + i * 4)
                                            : BitConverter.ToUInt16(ubulk, o + shift + i * 2);

                // Small blobs pad after the last real triangle, and those padding entries read as
                // index 0. Zero is a legal index, so the run walk happily continues into the
                // padding and manufactures a fistful of (0,0,0) triangles - which then tripped the
                // degeneracy rule and got the whole mesh rejected. SM_BS_Screen_Left_01 is 590
                // bytes with its 16 real indices at 530 and padding after them. Trim trailing
                // degenerate triangles before scoring; real geometry never ends in them.
                var end = usable;
                while (end >= 3)
                {
                    var a = idx[end - 3];
                    var b = idx[end - 2];
                    var c = idx[end - 1];
                    var ax = positions[a * 3]; var ay = positions[a * 3 + 1]; var az = positions[a * 3 + 2];
                    var bx = positions[b * 3]; var by = positions[b * 3 + 1]; var bz = positions[b * 3 + 2];
                    var cx = positions[c * 3]; var cy = positions[c * 3 + 1]; var cz = positions[c * 3 + 2];
                    var ux = bx - ax; var uy = by - ay; var uz = bz - az;
                    var vx = cx - ax; var vy = cy - ay; var vz = cz - az;
                    var nx = uy * vz - uz * vy;
                    var ny = uz * vx - ux * vz;
                    var nz = ux * vy - uy * vx;
                    if (nx * nx + ny * ny + nz * nz > 1e-12) break;
                    end -= 3;
                }
                if (end < 3) continue;
                if (end != usable)
                {
                    Array.Resize(ref idx, end);
                    usable = end;
                }

                var degen = DegenerateFraction(positions, idx);
                var tris = usable / 3;
                if (degen > 0.05) continue;
                var better = degen < bestDegen - 0.005 || (degen <= bestDegen + 0.005 && tris > bestTris);
                if (!better) continue;
                bestDegen = degen;
                bestTris = tris;
                best = idx;
                if (Verbose)
                    Console.Error.WriteLine($"[blob] indices @blob+{o - blobOffset}+{shift} n={usable} " +
                                            $"degen={degen * 100:0.00}%");
            }
            o = p - 4;
        }

        // A scrambled index buffer shows up as a large fraction of zero-area triangles.
        if (best is null && Verbose)
            Console.Error.WriteLine($"[blob] no self-validating index run in [{blobOffset + from}, {scanEnd})");
        return best;
    }

    private static double DegenerateFraction(float[] pos, uint[] indices)
    {
        var degenerate = 0;
        var total = 0;
        for (var i = 0; i + 2 < indices.Length; i += 3)
        {
            var a = (int)indices[i] * 3;
            var b = (int)indices[i + 1] * 3;
            var c = (int)indices[i + 2] * 3;
            total++;
            if (a + 2 >= pos.Length || b + 2 >= pos.Length || c + 2 >= pos.Length) { degenerate++; continue; }
            var ux = pos[b] - pos[a]; var uy = pos[b + 1] - pos[a + 1]; var uz = pos[b + 2] - pos[a + 2];
            var vx = pos[c] - pos[a]; var vy = pos[c + 1] - pos[a + 1]; var vz = pos[c + 2] - pos[a + 2];
            var nx = uy * vz - uz * vy;
            var ny = uz * vx - ux * vz;
            var nz = ux * vy - uy * vx;
            if (nx * nx + ny * ny + nz * nz < 1e-12) degenerate++;
        }
        return total == 0 ? 1.0 : (double)degenerate / total;
    }

    private static float[] SmoothNormals(float[] pos, uint[] indices)
    {
        var nrm = new float[pos.Length];
        for (var i = 0; i + 2 < indices.Length; i += 3)
        {
            var a = (int)indices[i] * 3;
            var b = (int)indices[i + 1] * 3;
            var c = (int)indices[i + 2] * 3;
            if (a < 0 || b < 0 || c < 0 || a + 2 >= pos.Length || b + 2 >= pos.Length || c + 2 >= pos.Length)
                continue;
            var ux = pos[b] - pos[a]; var uy = pos[b + 1] - pos[a + 1]; var uz = pos[b + 2] - pos[a + 2];
            var vx = pos[c] - pos[a]; var vy = pos[c + 1] - pos[a + 1]; var vz = pos[c + 2] - pos[a + 2];
            var nx = uy * vz - uz * vy;
            var ny = uz * vx - ux * vz;
            var nz = ux * vy - uy * vx;

            nrm[a] += nx; nrm[a + 1] += ny; nrm[a + 2] += nz;
            nrm[b] += nx; nrm[b + 1] += ny; nrm[b + 2] += nz;
            nrm[c] += nx; nrm[c + 1] += ny; nrm[c + 2] += nz;
        }
        for (var i = 0; i + 2 < nrm.Length; i += 3)
        {
            var len = MathF.Sqrt(nrm[i] * nrm[i] + nrm[i + 1] * nrm[i + 1] + nrm[i + 2] * nrm[i + 2]);
            if (len < 1e-9f) { nrm[i] = 0; nrm[i + 1] = 0; nrm[i + 2] = 1; continue; }
            nrm[i] /= len; nrm[i + 1] /= len; nrm[i + 2] /= len;
        }
        return nrm;
    }

    // ------------------------------------------------------------------ diagnostics

    public static int CmdLodTest(IFileProvider provider, string[] args)
    {
        if (args.Length == 0) { Console.Error.WriteLine("usage: dfmap lodtest <meshObjectPath> [...]"); return 2; }
        var stats = new Stats();
        var results = new List<object>();
        foreach (var p in args)
        {
            var md = Decode(provider, p, stats);
            Console.WriteLine(p);
            if (md is null) { Console.WriteLine("  NOT DECODED"); continue; }
            Console.WriteLine($"  {md.VertexCount} vertices, {md.TriangleCount} triangles");
            Console.WriteLine($"  bounds ({md.BoundsMin[0]:0.##},{md.BoundsMin[1]:0.##},{md.BoundsMin[2]:0.##}).." +
                              $"({md.BoundsMax[0]:0.##},{md.BoundsMax[1]:0.##},{md.BoundsMax[2]:0.##})");
            results.Add(md.Path);
        }
        Console.WriteLine($"\ndecoded {stats.Decoded}/{stats.Attempted}");
        return results.Count > 0 ? 0 : 1;
    }
}
