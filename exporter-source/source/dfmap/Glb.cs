using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Dfmap;

/// <summary>
/// Minimal dependency-free glTF 2.0 / GLB writer for a static instanced scene.
///
/// UE (Z-up, centimetres) -> glTF (Y-up, metres): (x,y,z) -> (x,z,y)*0.01.
/// Blender's glTF import then produces UE (x,-y,z)*0.01. This matches the independently
/// verified UEFormat v10 mirror convention. The mirror already changes handedness, so
/// triangle indices must not be reversed a second time. Native affine transforms are
/// conjugated by the same axis permutation; do not replace them with Euler round trips.
///
/// Positions are scaled to metres by UnitScale; normals and other directions must NOT be.
/// </summary>
public sealed class GlbWriter
{
    // Derived, not guessed. Two constraints fix this matrix completely:
    //   1. glTF is Y-up, so glTF Y must carry UE Z (the height).
    //   2. Moving from UE's left-handed system to Blender's right-handed one with the SAME up
    //      axis needs a mirror, so det = -1. UEFormat uses exactly that for v10 mesh data
    //      (_POS_MIRROR = (1,-1,1)).
    // The only matrix satisfying both is the one below, and Blender's glTF importer then yields
    // (ue_x, -ue_y, ue_z) - i.e. UEFormat's convention, reached through glTF rather than through
    // a .uemodel. Getting constraint 1 wrong (putting UE Z into glTF Z) lays the scene on its
    // side; getting constraint 2 wrong (det = +1) mirrors it.
    private static readonly double[][] C =
    {
        new[] { 1.0, 0.0, 0.0 },
        new[] { 0.0, 0.0, 1.0 },
        new[] { 0.0, 1.0, 0.0 },
    };

    private readonly List<MeshData> _meshes = new();
    private readonly Dictionary<string, int> _meshIndex = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<(int Mesh, float[] Matrix)> _nodes = new();
    private readonly List<string> _nodeNames = new();
    private readonly List<SourceInstanceMetadata> _nodeSources = new();

    // glTF materials, deduplicated by Unreal material instance path
    private readonly List<(string Name, string Path)> _materials = new();
    private readonly Dictionary<string, int> _materialIndex = new(StringComparer.OrdinalIgnoreCase);

    // images/textures referenced by those materials (relative PNG paths written by TextureCache)
    private readonly List<string> _images = new();
    private readonly Dictionary<string, int> _imageIndex = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<int, (int Bc, int Nrm, int Mra)> _materialTextures = new();
    private readonly Dictionary<int, float[]> _materialTint = new();

    /// <summary>material path -> relative PNG paths, filled in by the caller after decoding.</summary>
    public Dictionary<string, (string BaseColor, string Normal, string Mra, float[] Tint)> MaterialTextureFiles { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// Prepended to every image URI. Files written into a subdirectory of the output folder need
    /// "../" so they still resolve the textures/ directory that the main scene.glb uses.
    /// </summary>
    public string ImageUriPrefix { get; set; } = "";

    /// <summary>Lights exported through KHR_lights_punctual.</summary>
    public List<LightInstance> Lights { get; set; } = new();

    /// <summary>Lights glTF cannot express (sky, fog) - reported instead of silently dropped.</summary>
    public Dictionary<string, int> UnsupportedLights { get; } = new(StringComparer.OrdinalIgnoreCase);

    public int MeshCount => _meshes.Count;
    public int NodeCount => _nodes.Count;
    public int MaterialCount => _materials.Count;
    public int ImageCount => _images.Count;

    private int ImageSlot(string relPath)
    {
        if (string.IsNullOrEmpty(relPath)) return -1;
        if (_imageIndex.TryGetValue(relPath, out var i)) return i;
        i = _images.Count;
        _images.Add(relPath);
        _imageIndex[relPath] = i;
        return i;
    }

    private int MaterialSlot(string path, string fallbackName)
    {
        if (string.IsNullOrEmpty(path))
        {
            if (!_materialIndex.TryGetValue("__default__", out var d))
            {
                d = _materials.Count;
                _materials.Add(("default", ""));
                _materialIndex["__default__"] = d;
            }
            return d;
        }
        if (_materialIndex.TryGetValue(path, out var i)) return i;
        i = _materials.Count;
        var name = !string.IsNullOrEmpty(fallbackName) ? fallbackName : path[(path.LastIndexOf('.') + 1)..];
        _materials.Add((name, path));
        _materialIndex[path] = i;

        if (MaterialTextureFiles.TryGetValue(path, out var tex))
        {
            var bc = ImageSlot(tex.BaseColor);
            var nrm = ImageSlot(tex.Normal);
            var mra = ImageSlot(tex.Mra);
            if (bc >= 0 || nrm >= 0 || mra >= 0) _materialTextures[i] = (bc, nrm, mra);
            if (tex.Tint is not null) _materialTint[i] = tex.Tint;
        }
        return i;
    }

    public int AddMesh(MeshData m)
    {
        if (_meshIndex.TryGetValue(m.Path, out var i)) return i;
        _meshes.Add(m);
        _meshIndex[m.Path] = _meshes.Count - 1;
        return _meshes.Count - 1;
    }

    /// <summary>loc = UE world location (cm), rot = UE roll/pitch/yaw (deg), scale = UE scale.</summary>
    public void AddInstance(int meshIndex, float[] loc, float[] rot, float[] scale, string name, float[] matrixUE = null,
                            SourceInstanceMetadata source = null)
    {
        var m = matrixUE is null ? BuildNodeMatrix(loc, rot, scale) : ConvertNativeMatrix(matrixUE);
        _nodes.Add((meshIndex, m));
        _nodeNames.Add(name);
        _nodeSources.Add(source);
    }

    public static float[] ConvertNativeMatrix(float[] matrixUE)
    {
        if (matrixUE.Length != 16) throw new ArgumentException("Expected a 4x4 UE column-major matrix");
        // C swaps UE Y/Z. The same permutation applies to rows and columns;
        // only translation is scaled from centimetres to metres.
        var permutation = new[] { 0, 2, 1, 3 };
        var result = new float[16];
        for (var column = 0; column < 4; column++)
            for (var row = 0; row < 4; row++)
                result[column * 4 + row] = matrixUE[permutation[column] * 4 + permutation[row]]
                    * (column == 3 && row < 3 ? 0.01f : 1f);
        return result;
    }

    /// <summary>UE placement transform -> glTF column-major 4x4, axis-converted.</summary>
    public static float[] BuildNodeMatrix(float[] loc, float[] rot, float[] scale)
    {
        double sx = scale?[0] ?? 1f, sy = scale?[1] ?? 1f, sz = scale?[2] ?? 1f;
        var R = UeFormat.RotationMatrix(rot?[0] ?? 0f, rot?[1] ?? 0f, rot?[2] ?? 0f);
        var A = new double[3][];
        for (var r = 0; r < 3; r++)
        {
            A[r] = new[] { R[r][0] * sx, R[r][1] * sy, R[r][2] * sz };
        }

        // A' = C * A * C^T (C is orthonormal, so C^T = C^-1).
        var CA = Mul(C, A);
        var A2 = Mul(CA, Transpose(C));

        var t = new double[3];
        var lv = loc ?? new float[] { 0, 0, 0 };
        for (var r = 0; r < 3; r++) t[r] = (C[r][0] * lv[0] + C[r][1] * lv[1] + C[r][2] * lv[2]) * UnitScale;

        // glTF matrices are column-major
        return new[]
        {
            (float)A2[0][0], (float)A2[1][0], (float)A2[2][0], 0f,
            (float)A2[0][1], (float)A2[1][1], (float)A2[2][1], 0f,
            (float)A2[0][2], (float)A2[1][2], (float)A2[2][2], 0f,
            (float)t[0], (float)t[1], (float)t[2], 1f,
        };
    }

    public void Write(string path, string sceneName)
    {
        // ---- binary buffer ----
        using var bin = new MemoryStream();
        var views = new JArray();
        var accessors = new JArray();
        var gltfMeshes = new JArray();

        foreach (var m in _meshes)
        {
            var pos = AxisConvert(m.Positions, 3);
            var nrm = AxisConvertDirection(m.Normals, 3);
            var uv = m.Uvs;

            // The axis map has determinant -1: it is a mirror, which is what moving from a
            // left-handed (UE) to a right-handed (Blender) system with the SAME up axis requires.
            // UEFormat does exactly this for v10 mesh data (_POS_MIRROR = (1,-1,1)). A mirror
            // already reverses triangle orientation, so the index order is left ALONE - swapping
            // it as well is the double flip that put every face inside-out.
            var idx = new uint[m.Indices.Length];
            Array.Copy(m.Indices, idx, m.Indices.Length);

            // The two decode paths disagree about which way their normals point - Unreal's own
            // packed normals versus the ones this tool smooths out of the .ubulk - and a mesh
            // whose normals oppose its faces shades from behind, which reads as a broken model.
            // Rather than trusting either source, flip the whole normal array when it opposes
            // the winding that was just verified.
            if (NormalsOpposeWinding(pos, nrm, idx))
                for (var i = 0; i < nrm.Length; i++) nrm[i] = -nrm[i];

            var (pMin, pMax) = MinMax(pos, 3);
            var posAcc = AddAccessor(bin, views, accessors, pos, 5126, "VEC3", target: 34962, min: pMin, max: pMax);
            var nrmAcc = AddAccessor(bin, views, accessors, nrm, 5126, "VEC3", target: 34962);
            var uvAcc = AddAccessor(bin, views, accessors, uv, 5126, "VEC2", target: 34962);
            var attributes = new JObject { ["POSITION"]=posAcc,["NORMAL"]=nrmAcc,["TEXCOORD_0"]=uvAcc };
            if(m.Colors?.Length==m.VertexCount*4)
                attributes["COLOR_0"]=AddAccessor(bin,views,accessors,m.Colors.Select(c=>c/255f).ToArray(),5126,"VEC4",target:34962);
            if(m.UvChannels is not null)
                for(var channel=1;channel<m.UvChannels.Length;channel++)
                    if(m.UvChannels[channel]?.Length==m.VertexCount*2)
                        attributes["TEXCOORD_"+channel]=AddAccessor(bin,views,accessors,m.UvChannels[channel],5126,"VEC2",target:34962);

            // Split the triangle list per material so glTF (and therefore Blender) gets real
            // material slots. Streamed meshes also use the independently verified section
            // table when available; only an absent table falls back to material 0.
            var triangles = idx.Length / 3;
            var groups = new SortedDictionary<int, List<uint>>();
            for (var t = 0; t < triangles; t++)
            {
                var slot = m.FaceMaterial is not null && t < m.FaceMaterial.Length ? m.FaceMaterial[t] : 0;
                if (!groups.TryGetValue(slot, out var list)) groups[slot] = list = new List<uint>();
                list.Add(idx[t * 3]);
                list.Add(idx[t * 3 + 1]);
                list.Add(idx[t * 3 + 2]);
            }

            var prims = new JArray();
            foreach (var (slot, list) in groups)
            {
                var matPath = slot >= 0 && slot < m.Materials.Count ? m.Materials[slot] : null;
                var gltfSlot = MaterialSlot(matPath, matPath is not null
                    ? Path.GetFileNameWithoutExtension(matPath)
                    : null);
                var acc = AddAccessor(bin, views, accessors, list.ToArray(), 5125, "SCALAR", target: 34963);
                prims.Add(new JObject
                {
                    ["attributes"] = attributes.DeepClone(),
                    ["indices"] = acc,
                    ["material"] = gltfSlot,
                    ["mode"] = 4,
                });
            }

            gltfMeshes.Add(new JObject
            {
                ["name"] = m.Path,
                ["primitives"] = prims,
                ["extras"] = new JObject { ["unrealVertexColorState"] = m.ColorBufferState,
                                            ["unrealMeshPath"] = m.SourceAssetPath ?? m.Path },
            });
        }

        // ---- nodes ----
        var nodes = new JArray();
        var rootChildren = new JArray();
        for (var i = 0; i < _nodes.Count; i++)
        {
            var node=new JObject
            {
                ["name"] = _nodeNames[i],
                ["mesh"] = _nodes[i].Mesh,
                ["matrix"] = new JArray(_nodes[i].Matrix.Select(x => (JToken)x)),
            };
            if(_nodeSources[i] is {} source)node["extras"]=new JObject{["dfmap"]=source.ToJson()};
            nodes.Add(node);
            rootChildren.Add(i + 1);   // node 0 is the root
        }
        var root = new JObject { ["name"] = sceneName, ["children"] = rootChildren };
        nodes.Insert(0, root);

        // ---- lights (KHR_lights_punctual) ----
        var lightDefs = new JArray();
        var lightNodes = new JArray();
        foreach (var l in Lights ?? new List<LightInstance>())
        {
            string kind = l.Type switch
            {
                "Directional" => "directional",
                "Spot" => "spot",
                "Point" or "Rect" => "point",   // glTF has no area light; Rect is approximated
                _ => null,
            };
            if (kind is null)
            {
                UnsupportedLights[l.Type] = UnsupportedLights.GetValueOrDefault(l.Type) + 1;
                continue;
            }
            var def = new JObject
            {
                ["name"] = l.Name,
                ["type"] = kind,
                ["color"] = new JArray(l.Color ?? new[] { 1f, 1f, 1f }),
                ["intensity"] = Math.Max(l.Intensity, 0f),
            };
            if (kind != "directional" && l.Radius > 0) def["range"] = l.Radius * UnitScale;
            if (kind == "spot")
            {
                var outer = Math.Clamp(l.OuterCone, 1f, 89f) * MathF.PI / 180f;
                var inner = Math.Clamp(l.InnerCone, 0f, l.OuterCone) * MathF.PI / 180f;
                def["spot"] = new JObject { ["innerConeAngle"] = inner, ["outerConeAngle"] = outer };
            }
            if (l.Type == "Rect")
                def["extras"] = new JObject
                {
                    ["unrealType"] = "RectLight",
                    ["sourceWidthCm"] = l.SourceWidth,
                    ["sourceHeightCm"] = l.SourceHeight,
                    ["note"] = "approximated as a point light; glTF has no rectangular area light",
                };

            var idx = lightDefs.Count;
            lightDefs.Add(def);
            lightNodes.Add(new JObject
            {
                ["name"] = l.Name,
                ["matrix"] = new JArray(BuildNodeMatrix(l.Loc, l.Rot, new[] { 1f, 1f, 1f }).Select(x => (JToken)x)),
                ["extensions"] = new JObject
                {
                    ["KHR_lights_punctual"] = new JObject { ["light"] = idx },
                },
            });
        }
        foreach (var ln in lightNodes) { nodes.Add(ln); rootChildren.Add(nodes.Count - 1); }

        var gltf = new JObject
        {
            ["asset"] = new JObject { ["version"] = "2.0", ["generator"] = "dfmap" },
            ["scene"] = 0,
            ["scenes"] = new JArray { new JObject { ["name"] = sceneName, ["nodes"] = new JArray { 0 } } },
            ["nodes"] = nodes,
            ["meshes"] = gltfMeshes,
            ["materials"] = new JArray(_materials.Select((m, idx) =>
            {
                var mat = new JObject
                {
                    ["name"] = m.Name,
                    ["extras"] = new JObject { ["unrealMaterialPath"] = m.Path },
                    ["pbrMetallicRoughness"] = new JObject
                    {
                        // The material's UE BaseColorScaler tint, when it declares one, is the
                        // multiplier the game applies to the albedo map; omitting it leaves the
                        // scene washed out compared with the game.
                        ["baseColorFactor"] = _materialTint.TryGetValue(idx, out var tint)
                            ? new JArray(tint[0], tint[1], tint[2], tint[3] > 0f ? tint[3] : 1.0)
                            : new JArray(1.0, 1.0, 1.0, 1.0),
                        ["metallicFactor"] = 1.0,
                        ["roughnessFactor"] = 1.0,
                    },
                    ["doubleSided"] = true,
                };
                if (_materialTextures.TryGetValue(idx, out var t))
                {
                    var pbr = (JObject)mat["pbrMetallicRoughness"];
                    if (t.Bc >= 0) pbr["baseColorTexture"] = new JObject { ["index"] = t.Bc };
                    if (t.Nrm >= 0) mat["normalTexture"] = new JObject { ["index"] = t.Nrm };
                    if (t.Mra >= 0)
                    {
                        pbr["metallicRoughnessTexture"] = new JObject { ["index"] = t.Mra };
                    }
                    else
                    {
                        // glTF's defaults are metalness 1 / roughness 1, i.e. a perfect mirror.
                        // Game ships its MRA maps only as streaming virtual textures, whose
                        // pixel data cannot be reassembled, so without an explicit dielectric
                        // default every surface renders as polished chrome.
                        pbr["metallicFactor"] = 0.0;
                        pbr["roughnessFactor"] = 0.65;
                    }
                }
                else
                {
                    // Untextured: same reasoning, these are painted metal and concrete.
                    var pbr = (JObject)mat["pbrMetallicRoughness"];
                    pbr["metallicFactor"] = 0.0;
                    pbr["roughnessFactor"] = 0.65;
                }
                return (JToken)mat;
            })),
            ["textures"] = new JArray(_images.Select((_, i) => (JToken)new JObject { ["sampler"] = 0, ["source"] = i })),
            ["samplers"] = new JArray { new JObject { ["magFilter"] = 9729, ["minFilter"] = 9987, ["wrapS"] = 10497, ["wrapT"] = 10497 } },
            ["images"] = new JArray(_images.Select(p => (JToken)new JObject { ["uri"] = ImageUriPrefix + p })),
            ["extensionsUsed"] = new JArray("KHR_lights_punctual"),
            ["extensions"] = new JObject
            {
                ["KHR_lights_punctual"] = new JObject { ["lights"] = lightDefs },
            },
            ["accessors"] = accessors,
            ["bufferViews"] = views,
            ["buffers"] = new JArray { new JObject { ["byteLength"] = bin.Length } },
        };

        // ---- GLB container ----
        var jsonBytes = Encoding.UTF8.GetBytes(gltf.ToString(Formatting.None));
        var jsonPad = (4 - jsonBytes.Length % 4) % 4;
        var binBytes = bin.ToArray();
        var binPad = (4 - binBytes.Length % 4) % 4;

        using var fs = File.Create(path);
        using var w = new BinaryWriter(fs);
        w.Write(0x46546C67);                                     // "glTF"
        w.Write(2);
        w.Write(12 + 8 + jsonBytes.Length + jsonPad + 8 + binBytes.Length + binPad);
        w.Write(jsonBytes.Length + jsonPad);
        w.Write(0x4E4F534A);                                     // "JSON"
        w.Write(jsonBytes);
        for (var i = 0; i < jsonPad; i++) w.Write((byte)0x20);
        w.Write(binBytes.Length + binPad);
        w.Write(0x004E4942);                                     // "BIN\0"
        w.Write(binBytes);
        for (var i = 0; i < binPad; i++) w.Write((byte)0);
    }

    // ---------------------------------------------------------------- helpers

    private static int AddAccessor(MemoryStream bin, JArray views, JArray accessors,
                                   Array data, int componentType, string type, int target = 0,
                                   double[] min = null, double[] max = null)
    {
        var elementSize = componentType switch { 5126 => 4, 5125 => 4, 5123 => 2, _ => 4 };
        var components = type switch { "VEC4" => 4, "VEC3" => 3, "VEC2" => 2, _ => 1 };
        var bytes = data.Length * elementSize;
        var offset = bin.Position;

        var buf = new byte[bytes];
        Buffer.BlockCopy(data, 0, buf, 0, bytes);
        bin.Write(buf);

        views.Add(new JObject
        {
            ["buffer"] = 0,
            ["byteOffset"] = offset,
            ["byteLength"] = bytes,
            ["target"] = target,
        });

        var acc = new JObject
        {
            ["bufferView"] = views.Count - 1,
            ["componentType"] = componentType,
            ["count"] = data.Length / components,
            ["type"] = type,
        };
        if (min is not null) acc["min"] = new JArray(min.Select(x => (JToken)x));
        if (max is not null) acc["max"] = new JArray(max.Select(x => (JToken)x));
        accessors.Add(acc);
        return accessors.Count - 1;
    }

    /// <summary>
    /// UE (left-handed, Z-up, centimetres) -> glTF (right-handed, Y-up, METRES).
    /// The axis mapping is the one Unreal's own glTF exporter uses; the 0.01 factor is
    /// required because glTF defines its unit as metres, so Blender would otherwise import
    /// the map 100x too large.
    /// </summary>
    public const float UnitScale = 0.01f;

    /// <summary>
    /// True when a mesh's vertex normals mostly point against the triangles they belong to.
    /// Face orientation is taken from the (already reversed, already verified) index buffer, so
    /// this is a self-consistency check rather than a second opinion about the convention.
    /// </summary>
    private static bool NormalsOpposeWinding(float[] pos, float[] nrm, uint[] idx)
    {
        if (pos is null || nrm is null || idx is null) return false;
        if (nrm.Length != pos.Length || pos.Length < 9) return false;
        double sum = 0;
        var counted = 0;
        for (var t = 0; t + 2 < idx.Length; t += 3)
        {
            var a = (int)idx[t] * 3;
            var b = (int)idx[t + 1] * 3;
            var c = (int)idx[t + 2] * 3;
            if (a + 2 >= pos.Length || b + 2 >= pos.Length || c + 2 >= pos.Length) continue;
            var e1x = pos[b] - pos[a];
            var e1y = pos[b + 1] - pos[a + 1];
            var e1z = pos[b + 2] - pos[a + 2];
            var e2x = pos[c] - pos[a];
            var e2y = pos[c + 1] - pos[a + 1];
            var e2z = pos[c + 2] - pos[a + 2];
            var fx = e1y * e2z - e1z * e2y;
            var fy = e1z * e2x - e1x * e2z;
            var fz = e1x * e2y - e1y * e2x;
            var len = Math.Sqrt(fx * fx + fy * fy + fz * fz);
            if (len < 1e-12) continue;
            var nx = nrm[a] + nrm[b] + nrm[c];
            var ny = nrm[a + 1] + nrm[b + 1] + nrm[c + 1];
            var nz = nrm[a + 2] + nrm[b + 2] + nrm[c + 2];
            sum += (fx * nx + fy * ny + fz * nz) / len;
            counted++;
        }
        return counted > 8 && sum < 0;
    }

    public static float[] AxisConvert(float[] src, int stride) => AxisConvert(src, stride, UnitScale);

    /// <summary>Same axis mapping without the unit scale - used for normals, which are unitless.</summary>
    public static float[] AxisConvertDirection(float[] src, int stride) => AxisConvert(src, stride, 1f);

    private static float[] AxisConvert(float[] src, int stride, float scale)
    {
        // Driven by C rather than by a second hand-written copy of the axis map: the two had
        // drifted apart, so the instance transforms and the vertex data were being converted
        // by different rules.
        var dst = new float[src.Length];
        for (var i = 0; i + stride - 1 < src.Length; i += stride)
        {
            var x = src[i];
            var y = stride > 1 ? src[i + 1] : 0f;
            var z = stride > 2 ? src[i + 2] : 0f;
            dst[i] = (float)((C[0][0] * x + C[0][1] * y + C[0][2] * z) * scale);
            if (stride > 1) dst[i + 1] = (float)((C[1][0] * x + C[1][1] * y + C[1][2] * z) * scale);
            if (stride > 2) dst[i + 2] = (float)((C[2][0] * x + C[2][1] * y + C[2][2] * z) * scale);
        }
        return dst;
    }

    private static (double[], double[]) MinMax(float[] src, int stride)
    {
        var min = new[] { double.MaxValue, double.MaxValue, double.MaxValue };
        var max = new[] { double.MinValue, double.MinValue, double.MinValue };
        for (var i = 0; i + stride - 1 < src.Length; i += stride)
            for (var a = 0; a < stride; a++)
            {
                var v = src[i + a];
                if (v < min[a]) min[a] = v;
                if (v > max[a]) max[a] = v;
            }
        return (min, max);
    }

    private static double[][] Mul(double[][] a, double[][] b)
    {
        var r = new double[3][];
        for (var i = 0; i < 3; i++)
        {
            r[i] = new double[3];
            for (var j = 0; j < 3; j++)
                for (var k = 0; k < 3; k++)
                    r[i][j] += a[i][k] * b[k][j];
        }
        return r;
    }

    private static double[][] Transpose(double[][] a) => new[]
    {
        new[] { a[0][0], a[1][0], a[2][0] },
        new[] { a[0][1], a[1][1], a[2][1] },
        new[] { a[0][2], a[1][2], a[2][2] },
    };
}
