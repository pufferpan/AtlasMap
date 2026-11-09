using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse_Conversion.Textures;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Dfmap;

/// <summary>The texture maps a Game scene material instance points at.</summary>
public sealed class MaterialInfo
{
    public string Path { get; set; }
    public string BaseColor { get; set; }   // BaseColorMap
    public string Normal { get; set; }      // NormalMap
    public string Mra { get; set; }         // MRAMap - metallic / roughness / occlusion

    /// <summary>Linear RGBA multiplier the material applies to the albedo map, when declared.</summary>
    public float[] Tint { get; set; }
    public string MasterPath { get; set; }
    public Dictionary<string,string> TextureParameters { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string,float[]> VectorParameters { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string,float> ScalarParameters { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string,bool> SwitchParameters { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public sealed class TextureFile
{
    public string RelativePath { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public long Bytes { get; set; }
}

/// <summary>
/// Resolves UMaterialInstance texture parameters and decodes the referenced UTexture2D assets
/// to PNG files beside the scene, so glTF - and therefore Blender - gets real textures.
///
/// Material properties are read through CUE4Parse's own JSON converters (the same path the
/// `dump` command uses) rather than typed accessors, because the typed fields for this game
/// build are not reliably populated.
/// </summary>
public sealed class TextureCache
{
    private readonly IFileProvider _provider;
    private readonly string _outDir;
    private readonly string _texDirName;
    private readonly int _maxSize;
    private readonly JsonSerializerSettings _json;
    private readonly Dictionary<string, MaterialInfo> _materials = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, TextureFile> _textures = new(StringComparer.OrdinalIgnoreCase);
    private Dictionary<string, List<string>> _filesByDirectory;
    public readonly List<string> Failures = new();

    public TextureCache(IFileProvider provider, string outDir, string texDirName = "textures", int maxSize = 1024)
    {
        _provider = provider;
        _outDir = outDir;
        _texDirName = texDirName;
        _maxSize = maxSize;
        _json = Inspect.BuildJsonSettings(provider);
    }

    public int DecodedCount => _textures.Values.Count(t => t is not null);
    public long TotalBytes => _textures.Values.Where(t => t is not null).Sum(t => t.Bytes);

    /// <summary>Resolve a material instance path to its texture object paths.</summary>
    public MaterialInfo Material(string path)
    {
        if (string.IsNullOrEmpty(path)) return null;
        if (_materials.TryGetValue(path, out var cached)) return cached;
        var info = new MaterialInfo { Path = path };
        _materials[path] = info;

        try
        {
            var settings = JsonSerializer.Create(_json);
            var current = path;
            for (var depth = 0; depth < 4 && !string.IsNullOrEmpty(current); depth++)
            {
                var (pkgPath, objName) = MeshCache.SplitObjectPath(current);
                var obj = _provider.SafeLoadPackageObject(pkgPath, objName);
                if (obj is null) break;
                info.MasterPath=current;
                var json = JObject.FromObject(obj, settings);
                var props = json["Properties"] as JObject;
                if (props is null) break;

                if (props["TextureParameterValues"] is JArray values)
                {
                    // Parameter names are not consistent across Game's material families.
                    // Simple props use BaseColorMap / NormalMap / MRAMap, but everything built on
                    // a MatBlend master (M_MatBlend_Ground_Master and friends) names its layers by
                    // channel - "01_R_Base", "01_R_MRA", "02_G_Base" - so matching only the legacy
                    // names silently drops every layered material in the map.
                    var best = new Dictionary<string, (int Layer, string Path)>();
                    foreach (var v in values)
                    {
                        var name = v["ParameterInfo"]?["Name"]?.Value<string>();
                        var target = TextureObjectPath(v["ParameterValue"] as JObject);
                        if (name is null || target is null) continue;
                        info.TextureParameters.TryAdd(name,target);
                        var slot = SlotOf(name);
                        if (slot is null) continue;
                        var layer = LayerOf(name);
                        if (best.TryGetValue(slot, out var cur) && cur.Layer <= layer) continue;
                        best[slot] = (layer, target);
                    }
                    if (best.TryGetValue("C", out var c)) info.BaseColor ??= c.Path;
                    if (best.TryGetValue("N", out var n)) info.Normal ??= n.Path;
                    if (best.TryGetValue("MRA", out var m)) info.Mra ??= m.Path;
                }

                // Fallback: the material lists its own texture names. Used only when the
                // parameter table produced nothing for the base colour slot, and only when the
                // guessed asset actually exists - a wrong guess would otherwise occupy the slot
                // and block the correct texture found further up the parent chain.
                if (props["TextureStreamingData"] is JArray streaming && info.BaseColor is null)
                {
                    foreach (var entry in streaming)
                    {
                        var texName = entry["TextureName"]?.Value<string>();
                        if (texName is null || SlotOf(texName) != "C") continue;
                        var guess = GuessPath(path, texName);
                        if (guess is not null && _provider.Files.ContainsKey(guess + ".uasset"))
                        {
                            info.BaseColor = guess;
                            break;
                        }
                    }
                }

                if (props["VectorParameterValues"] is JArray vectors)
                {
                    foreach (var v in vectors)
                    {
                        var name = v["ParameterInfo"]?["Name"]?.Value<string>();
                        var rgba=v["ParameterValue"] as JObject;
                        if(name is not null&&rgba is not null)
                            info.VectorParameters.TryAdd(name,new[]{rgba["R"]?.Value<float>()??0,rgba["G"]?.Value<float>()??0,rgba["B"]?.Value<float>()??0,rgba["A"]?.Value<float>()??0});
                        if (name is not "BaseColorScaler" and not "BaseColorTint" and not "BaseColor"
                            and not "Tint" and not "BaseColorMultiplier") continue;
                        var value = v["ParameterValue"] as JObject;
                        if (value is null) continue;
                        float C(string k, float d) => value[k]?.Value<float>() ?? d;
                        info.Tint ??= new[] { C("R", 1f), C("G", 1f), C("B", 1f), C("A", 1f) };
                    }
                }

                if(props["ScalarParameterValues"] is JArray scalars)
                    foreach(var v in scalars)
                        if(v["ParameterInfo"]?["Name"]?.Value<string>() is {} name&&v["ParameterValue"] is {} value)
                            info.ScalarParameters.TryAdd(name,value.Value<float>());
                if(props["StaticParameters"]?["StaticSwitchParameters"] is JArray switches)
                    foreach(var v in switches)
                        if(v["ParameterInfo"]?["Name"]?.Value<string>() is {} name&&v["Value"] is {} value)
                            info.SwitchParameters.TryAdd(name,value.Value<bool>());

                var parent = props["Parent"] as JObject;
                current = TextureObjectPath(parent);
            }
        }
        catch (Exception ex)
        {
            if (Failures.Count < 40) Failures.Add($"{path}: {ex.GetType().Name}: {ex.Message}");
        }
        return info;
    }

    /// <summary>
    /// Which glTF slot a UE parameter or texture name feeds: "C" base colour, "N" normal,
    /// "MRA" packed metallic/roughness/occlusion, or null when it is something else entirely.
    /// Checked most-specific first so "BaseColorMap" cannot be mistaken for a normal map.
    /// </summary>
    private static string SlotOf(string name)
    {
        var n = name.ToLowerInvariant();
        var tokens = n.Split('_', StringSplitOptions.RemoveEmptyEntries);
        bool Has(params string[] keys) => keys.Any(k => n.Contains(k));
        bool Token(params string[] keys) => tokens.Any(t => keys.Contains(t));

        // Exact, well-known names are resolved before anything substring-based. "BaseColorMap"
        // contains "coloRMAp", so a naive search for "rma" classified every base colour map as a
        // metallic-roughness map and left almost every material without an albedo.
        if (Has("basecolor", "base_color", "basemap")) return "C";
        if (n is "decaltexture" or "bamap") return "C";
        if (n is "normaldecaltex") return "N";
        if (Has("normalmap", "normal_map")) return "N";
        if (Has("mramap", "mra_map", "_mra")) return "MRA";

        if (Has("normal", "norm", "nrm") || Token("n", "nr", "nrm", "nm", "nrml"))
            return "N";
        // "metallic" yes, bare "metal" no: it is a substring of MetalTrim, MetalSupport and
        // dozens of other prop names, which sent their base colour into the metallic slot.
        if (Token("mra", "orm", "rma", "mask", "msk", "rough", "ao")
            || Has("roughness", "metallic", "occlusion"))
            return "MRA";
        if (Has("albedo", "diffuse", "colour")
            || Token("base", "albedo", "diffuse", "diff", "c", "ca", "ch", "color"))
            return "C";
        return null;
    }

    /// <summary>
    /// The layer index a MatBlend parameter belongs to ("01_R_Base" -> 1). Single-layer
    /// materials return 0, so a layered material always prefers its first layer.
    /// </summary>
    private static int LayerOf(string name)
    {
        var m = System.Text.RegularExpressions.Regex.Match(name, @"(\d{1,2})_[RGBA]_");
        if (m.Success && int.TryParse(m.Groups[1].Value, out var v)) return v;
        return 0;
    }

    /// <summary>Resolve a bare texture name against the sibling folders of a material.</summary>
    private static string GuessPath(string materialPath, string textureName)
    {
        var slash = materialPath.LastIndexOf('/');
        if (slash < 0) return null;
        var dir = materialPath[..(slash + 1)];
        var trimmed = dir.TrimEnd('/');
        var up = trimmed.LastIndexOf('/');
        foreach (var d in new[] { dir, dir + "00_Textures/", up >= 0 ? trimmed[..(up + 1)] : dir })
            if (d is not null) return $"{d}{textureName}";
        return null;
    }

    /// <summary>Turn a serialized object reference into a loadable "Package.Object" path.</summary>
    private static string TextureObjectPath(JObject reference)
    {
        var objectName = reference?["ObjectName"]?.Value<string>();
        var objectPath = reference?["ObjectPath"]?.Value<string>();
        if (objectName is null || objectPath is null) return null;

        // ObjectName looks like "Texture2D'T_WalkwaySystem_MetalTrim_01_C_HD'"
        var quote = objectName.IndexOf('\'');
        var name = quote >= 0 ? objectName[(quote + 1)..].TrimEnd('\'') : objectName;
        // ObjectPath looks like "DeltaForce/Content/.../T_X.0" - drop the trailing export index
        var pkg = objectPath;
        var dot = pkg.LastIndexOf('.');
        if (dot > 0 && int.TryParse(pkg[(dot + 1)..], out _)) pkg = pkg[..dot];
        return $"{pkg}.{name}";
    }

    /// <summary>Decode a UTexture2D to a PNG under &lt;outDir&gt;/textures and return its info.</summary>
    public TextureFile Texture(string objectPath)
    {
        if (string.IsNullOrEmpty(objectPath)) return null;
        if (_textures.TryGetValue(objectPath, out var cached)) return cached;

        TextureFile file = null;
        var reasons = new List<string>();
        foreach (var candidate in Candidates(objectPath))
        {
            file = Decode(objectPath, candidate, out var why);
            if (file is not null) break;
            if (why is not null && reasons.Count < 4) reasons.Add(why);
        }
        _textures[objectPath] = file;
        if (file is null)
        {
            Missed++;
            var key = reasons.Count == 0 ? "no candidate at all" : string.Join(" + ", reasons.Distinct());
            lock (MissReasons) MissReasons[key] = MissReasons.GetValueOrDefault(key) + 1;
        }
        return file;
    }

    /// <summary>Textures that could not be decoded even after trying every sibling variant.</summary>
    public int Missed { get; private set; }

    /// <summary>
    /// Why textures were missed, bucketed. Without this a miss is invisible: the virtual-texture
    /// path returns null rather than throwing, so a run that loses two thirds of its textures
    /// produces no warnings at all and looks like it worked.
    /// </summary>
    public readonly Dictionary<string, int> MissReasons = new();

    /// <summary>Number of times a fallback sibling was used because the requested texture was unusable.</summary>
    public int Fallbacks { get; private set; }

    /// <summary>
    /// The requested texture, then its platform siblings.
    ///
    /// Game ships most HD textures as streaming virtual textures: the mip chain lives in
    /// .ubulk as VT tiles and CUE4Parse cannot reassemble it. Every such texture has siblings in
    /// the same folder holding the identical image as an ordinary cooked mip chain - e.g.
    /// "T_Foo_C_HD" (2048px VT) alongside "T_Foo_MAC" (1024px BC7 in .uptnl) - so those are
    /// decoded instead of dropping the material's base colour entirely.
    ///
    /// Sibling names are matched by stem + map-channel + platform token rather than by a
    /// trailing-suffix table, because the tokens are reordered between variants
    /// ("T_Foo_C_HD" vs "T_Foo_MAC") and the map channel must be preserved: handing the normal
    /// map to the base colour slot would tint the whole scene blue.
    /// </summary>
    private IEnumerable<string> Candidates(string objectPath)
    {
        yield return objectPath;

        var (pkg, name) = MeshCache.SplitObjectPath(objectPath);
        var slash = pkg.LastIndexOf('/');
        if (slash < 0) yield break;
        var dir = pkg[..(slash + 1)];

        var (stem, channel) = SplitChannels(name);
        if (stem.Length == 0) yield break;

        // The low-res platform variants sit one level up from the HD folder
        // ("00_Textures/HD/T_Foo_C_HD" vs "00_Textures/T_Foo_MAC"), so both are searched.
        var dirs = new List<string> { dir };
        var trimmed = dir.TrimEnd('/');
        var up = trimmed.LastIndexOf('/');
        if (up >= 0) dirs.Add(trimmed[..(up + 1)]);

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { name };
        var siblings = new List<(string Path, bool Virtual, long Size)>();
        _filesByDirectory ??= _provider.Files.Keys
            .Where(p => p.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
            .GroupBy(p => p[..(p.LastIndexOf('/')+1)], StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.ToList(), StringComparer.OrdinalIgnoreCase);
        foreach (var d in dirs)
        foreach (var f in _filesByDirectory.GetValueOrDefault(d) ?? Enumerable.Empty<string>())
        {
            if (!f.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)) continue;
            if (f.Length <= d.Length || !f.StartsWith(d, StringComparison.OrdinalIgnoreCase)) continue;
            var bare = f[(d.Length)..^".uasset".Length];
            if (bare.Contains('/')) continue;                          // this folder only
            if (!seen.Add(bare)) continue;
            if (!bare.StartsWith(stem, StringComparison.OrdinalIgnoreCase)) continue;

            var rest = bare[stem.Length..].Trim('_').ToUpperInvariant();
            if (rest.Length == 0) continue;

            // Every remaining token must be a known tag, no token may name a different map
            // channel than the one being requested, and a name with no channel token at all is
            // only acceptable for the base colour slot - that is what "_MAC" / "_CA" are.
            var tokens = rest.Split('_', StringSplitOptions.RemoveEmptyEntries);
            if (tokens.Length == 0) continue;
            var sawChannel = false;
            var ok = true;
            foreach (var t in tokens)
            {
                var kind = KindOf(t);
                if (kind is null) { if (!PlatformTags.Contains(t)) { ok = false; break; } continue; }
                if (kind != channel) { ok = false; break; }
                sawChannel = true;
            }
            if (!ok) continue;
            if (!sawChannel && channel != "C") continue;

            var virtualTex = false;
            long size = 0;
            try
            {
                var (sp, so) = MeshCache.SplitObjectPath($"{d}{bare}");   // needs the directory to resolve
                var t = _provider.SafeLoadPackageObject<UTexture2D>(sp, so);
                if (t is null) continue;
                virtualTex = t.GetOrDefault<bool>("VirtualTextureStreaming");
                size = f.Length;
                // The real payload lives beside the .uasset; prefer whichever sibling has the
                // most cooked pixel data.
                foreach (var ext in new[] { ".uptnl", ".ubulk" })
                    if (_provider.Files.TryGetValue(f[..^".uasset".Length] + ext, out var bulk))
                        size += bulk.Size;
            }
            catch { continue; }

            siblings.Add(($"{d}{bare}", virtualTex, size));
        }
        foreach (var s in siblings.Where(s => !s.Virtual).OrderByDescending(s => s.Size))
            yield return s.Path;
        foreach (var s in siblings.Where(s => s.Virtual).OrderByDescending(s => s.Size))
            yield return s.Path;
    }

    /// <summary>Channel token -> slot kind, or null when the token is a platform tag.</summary>
    private static string KindOf(string token) => token.ToUpperInvariant() switch
    {
        // "CH" is Game's colour+height packing, used all over Environment/Structures -
        // e.g. T_Foo_CH_HD. Leaving it out made SplitChannels treat "CH" as part of the stem, so
        // the sibling lookup searched for "T_Foo_CH*" and found nothing, while the material's
        // actual base colour sat right next to it as T_Foo_CH_HD.
        "C" or "CA" or "CH" or "D" or "BC" or "ALB" or "ALBEDO" or "DIFF" or "DIFFUSE" or "COLOR" or "BASE" => "C",
        "MAC" => "PACKED_MASK",
        "N" or "NR" or "NRM" or "NORMAL" or "NM" => "N",
        "MRA" or "MR" or "RMA" or "ORM" or "ARM" or "MASK" or "MSK" => "MRA",
        _ => null,
    };

    /// <summary>Tokens that only ever denote a streaming/platform variant.</summary>
    private static readonly HashSet<string> PlatformTags = new(
        new[] { "HD", "LD", "SD", "MOBILE", "EDITORSVT", "SVT", "NOSVT" }, StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// "T_Foo_C_HD" -> ("T_Foo", "C"); "T_Foo_MAC" -> ("T_Foo", "C"); "T_Foo_NR" -> ("T_Foo", "N").
    /// A trailing platform token is dropped first, then the channel token that precedes it.
    /// </summary>
    private static (string Stem, string Channel) SplitChannels(string name)
    {
        var parts = name.Split('_').ToList();
        if (parts.Count > 1 && PlatformTags.Contains(parts[^1])) parts.RemoveAt(parts.Count - 1);
        if (parts.Count > 1 && KindOf(parts[^1]) is { } kind)
        {
            parts.RemoveAt(parts.Count - 1);
            return (string.Join('_', parts), kind);
        }
        return (string.Join('_', parts), "C");
    }

    private TextureFile Decode(string requested, string candidate, out string why)
    {
        why = null;
        try
        {
            var (pkgPath, objName) = MeshCache.SplitObjectPath(candidate);
            var tex = _provider.SafeLoadPackageObject<UTexture2D>(pkgPath, objName);
            if (tex is null) { why = "asset not loadable"; return null; }
            if (tex.GetOrDefault<bool>("VirtualTextureStreaming"))
            {
                if(!VirtualTextureCompat.Repair(tex,out var virtualReason))
                { why=virtualReason??"streaming virtual texture metadata unavailable";return null; }
            }

            CTexture ctex;
            if(tex.PlatformData?.VTData is {} virtualData && virtualData.IsInitialized())
            {
                var mip=_maxSize>0?(int)Math.Max(0,Math.Ceiling(Math.Log2(Math.Max(virtualData.Width,virtualData.Height)/(double)_maxSize))):0;
                mip=Math.Min(mip,(int)virtualData.NumMips-1);
                ctex=tex.DecodeMip(mip,ETexturePlatform.DesktopMobile);
            }
            else ctex=_maxSize>0?tex.Decode(_maxSize,ETexturePlatform.DesktopMobile):tex.Decode(ETexturePlatform.DesktopMobile);
            if (ctex is null || ctex.Width == 0 || ctex.Height == 0) { why = "decode returned nothing"; return null; }

            var bgra = ctex.PixelFormat.ToString().Contains("B8G8R8A8", StringComparison.OrdinalIgnoreCase);
            var rgba = bgra ? SwapRb(ctex.Data) : ctex.Data;
            var w = ctex.Width;
            var h = ctex.Height;
            var pixels = rgba;

            if (_maxSize > 0 && Math.Max(w, h) > _maxSize)
            {
                var scale = (double)_maxSize / Math.Max(w, h);
                var nw = Math.Max(1, (int)(w * scale));
                var nh = Math.Max(1, (int)(h * scale));
                pixels = BoxDownsample(rgba, w, h, nw, nh);
                w = nw; h = nh;
            }

            Directory.CreateDirectory(Path.Combine(_outDir, _texDirName));
            // name the file after the texture the material asked for, so the material->image
            // mapping stays stable no matter which sibling supplied the pixels; overwriting
            // keeps re-runs from accumulating copies.
            var (_, wanted) = MeshCache.SplitObjectPath(requested);
            var identity=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
                System.Text.Encoding.UTF8.GetBytes(requested.ToLowerInvariant())))[..12].ToLowerInvariant();
            var name = SanitizeName(wanted) + "_" + identity + ".png";
            var full = Path.Combine(_outDir, _texDirName, name);
            MapImage.WritePng(full, pixels, w, h);
            if (!candidate.Equals(requested, StringComparison.OrdinalIgnoreCase)) Fallbacks++;

            return new TextureFile
            {
                RelativePath = $"{_texDirName}/{name}",
                Width = w,
                Height = h,
                Bytes = new FileInfo(full).Length,
            };
        }
        catch (Exception ex)
        {
            why = $"{ex.GetType().Name}";
            if (Failures.Count < 40)
                Failures.Add($"{candidate}{(candidate == requested ? "" : $" (fallback for {requested})")}: " +
                             $"{ex.GetType().Name}: {ex.Message}");
            return null;
        }
    }

    private static byte[] SwapRb(byte[] src)
    {
        var dst = (byte[])src.Clone();
        for (var i = 0; i + 3 < dst.Length; i += 4) (dst[i], dst[i + 2]) = (dst[i + 2], dst[i]);
        return dst;
    }

    private static byte[] BoxDownsample(byte[] src, int w, int h, int nw, int nh)
    {
        var dst = new byte[nw * nh * 4];
        var sx = (double)w / nw;
        var sy = (double)h / nh;
        for (var y = 0; y < nh; y++)
            for (var x = 0; x < nw; x++)
            {
                var x0 = (int)(x * sx); var x1 = Math.Min(w, (int)((x + 1) * sx));
                var y0 = (int)(y * sy); var y1 = Math.Min(h, (int)((y + 1) * sy));
                int r = 0, g = 0, b = 0, a = 0, n = 0;
                for (var yy = y0; yy < y1; yy++)
                    for (var xx = x0; xx < x1; xx++)
                    {
                        var o = (yy * w + xx) * 4;
                        r += src[o]; g += src[o + 1]; b += src[o + 2]; a += src[o + 3]; n++;
                    }
                if (n == 0) n = 1;
                var d = (y * nw + x) * 4;
                dst[d] = (byte)(r / n); dst[d + 1] = (byte)(g / n);
                dst[d + 2] = (byte)(b / n); dst[d + 3] = (byte)(a / n);
            }
        return dst;
    }

    private static string SanitizeName(string s)
    {
        var chars = s.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c).ToArray();
        return new string(chars);
    }
}
