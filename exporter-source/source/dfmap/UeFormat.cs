using System.Text;

namespace Dfmap;

/// <summary>
/// Writer for <b>UEFormat</b> .uemodel files - the intermediate format used by
/// h4lfheart/UEFormat and its Blender addon (Blender 4.2+), which is also the format
/// FModel and CUE4Parse can emit.
///
/// Spec: https://github.com/h4lfheart/UEFormat/blob/main/docs/uemodel.md
///       https://github.com/h4lfheart/UEFormat/blob/main/docs/generic.md
///
/// Everything is written in native Unreal units (centimetres, Z-up, left-handed) and the
/// addon converts to Blender space itself:
///     position * 0.01, then mirror Y  -> Blender (x, -y, z) in metres
/// (importer/create/space.py: _POS_MIRROR = (1.0, -1.0, 1.0)).
/// </summary>
public static class UeFormat
{
    public const byte FileVersion = 10;   // EUEFormatVersion.AttributeFormatRestructure

    public sealed class Material
    {
        public string Name = "";
        public string Path = "";
        public int FirstIndex;
        public int NumFaces;
    }

    public sealed class Lod
    {
        public string Name = "LOD0";
        public float[] Positions = Array.Empty<float>();   // 3 per vertex, UE cm
        public float[] Normals = Array.Empty<float>();     // 3 per vertex, unitless
        public float[] Uvs = Array.Empty<float>();         // 2 per vertex
        public uint[] Indices = Array.Empty<uint>();
        public List<Material> Materials = new();
    }

    public static void Write(string path, string objectName, string objectPath, IReadOnlyList<Lod> lods)
    {
        using var fs = File.Create(path);
        using var w = new BinaryWriter(fs, Encoding.UTF8);

        // ---- header (docs/generic.md) ----
        w.Write(Encoding.ASCII.GetBytes("UEFORMAT"));   // 8 bytes, no terminator
        WriteFString(w, "UEMODEL");
        w.Write(FileVersion);
        WriteFString(w, objectName);
        WriteFString(w, objectPath);
        w.Write((byte)0);                               // IsCompressed = false

        // ---- body: root FDataAttributeSet with a single LODS attribute ----
        w.Write(1);                                     // attribute count
        WriteFString(w, "LODS");
        var lodBytes = SerializeLods(lods);
        w.Write(lodBytes.Length);
        w.Write(lodBytes);
    }

    private static byte[] SerializeLods(IReadOnlyList<Lod> lods)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms, Encoding.UTF8);
        w.Write(lods.Count);
        foreach (var lod in lods) SerializeLod(w, lod);
        w.Flush();
        return ms.ToArray();
    }

    private static void SerializeLod(BinaryWriter w, Lod lod)
    {
        WriteFString(w, lod.Name);

        var count = lod.Positions.Length / 3;
        var attrs = new List<(string Name, byte[] Data)>
        {
            ("VERTICES", FloatArray(lod.Positions, 3)),
            ("INDICES", UIntArray(lod.Indices)),
            ("TEXCOORDS", TexCoords(lod.Uvs, count)),
            ("MATERIALS", Materials(lod.Materials)),
        };
        if (lod.Normals.Length == lod.Positions.Length) attrs.Insert(1, ("NORMALS", Normals(lod.Normals)));

        w.Write(attrs.Count);
        foreach (var (name, data) in attrs)
        {
            WriteFString(w, name);
            w.Write(data.Length);
            w.Write(data);
        }
    }

    /// <summary>TArray&lt;FVector&gt; = int32 count + count * 3 floats.</summary>
    private static byte[] FloatArray(float[] values, int components)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(values.Length / components);
        foreach (var v in values) w.Write(v);
        w.Flush();
        return ms.ToArray();
    }

    /// <summary>TArray&lt;uint&gt; = int32 count + count * uint32.</summary>
    private static byte[] UIntArray(uint[] values)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(values.Length);
        foreach (var v in values) w.Write(v);
        w.Flush();
        return ms.ToArray();
    }

    /// <summary>TArray&lt;FNormal&gt;; FNormal = float BinormalSign + FVector Normal.</summary>
    private static byte[] Normals(float[] normals)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(normals.Length / 3);
        for (var i = 0; i + 2 < normals.Length; i += 3)
        {
            w.Write(1f);                 // BinormalSign - the addon only uses it for tangents
            w.Write(normals[i]);
            w.Write(normals[i + 1]);
            w.Write(normals[i + 2]);
        }
        w.Flush();
        return ms.ToArray();
    }

    /// <summary>TArray&lt;FTexCoordEntry&gt;; each entry is a name plus TArray&lt;FMeshUVFloat&gt;.</summary>
    private static byte[] TexCoords(float[] uvs, int vertexCount)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(1);                      // one UV channel
        WriteFString(w, "UVChannel_1");
        var usable = Math.Min(vertexCount, uvs.Length / 2);
        w.Write(usable);
        for (var i = 0; i < usable * 2; i++) w.Write(uvs[i]);
        w.Flush();
        return ms.ToArray();
    }

    /// <summary>TArray&lt;FMaterial&gt;; each is name, path, FirstIndex, NumFaces.</summary>
    private static byte[] Materials(List<Material> materials)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(materials.Count);
        foreach (var m in materials)
        {
            WriteFString(w, m.Name);
            WriteFString(w, m.Path);
            w.Write(m.FirstIndex);
            w.Write(m.NumFaces);
        }
        w.Flush();
        return ms.ToArray();
    }

    /// <summary>
    /// UE rotation acting on COLUMN vectors. FRotationMatrix's stored axes
    /// use row-vector convention, so its published rows must be transposed.
    /// Checked independently against FTransform.TransformPosition/TransformVector.
    /// </summary>
    public static double[][] RotationMatrix(float rollDeg, float pitchDeg, float yawDeg)
    {
        double roll = rollDeg * Math.PI / 180.0;
        double pitch = pitchDeg * Math.PI / 180.0;
        double yaw = yawDeg * Math.PI / 180.0;
        double cp = Math.Cos(pitch), sp = Math.Sin(pitch);
        double cy = Math.Cos(yaw), sy = Math.Sin(yaw);
        double cr = Math.Cos(roll), sr = Math.Sin(roll);
        return new[]
        {
            new[] { cp * cy, sr * sp * cy - cr * sy, -(cr * sp * cy + sr * sy) },
            new[] { cp * sy, sr * sp * sy + cr * cy, cy * sr - cr * sp * sy },
            new[] { sp, -sr * cp, cr * cp },
        };
    }

    /// <summary>FString = int32 byte length + utf-8 bytes (no null terminator, no BOM).</summary>
    private static void WriteFString(BinaryWriter w, string s)
    {
        var bytes = Encoding.UTF8.GetBytes(s ?? "");
        w.Write(bytes.Length);
        w.Write(bytes);
    }
}
