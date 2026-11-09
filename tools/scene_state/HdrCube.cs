using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json;
using CUE4Parse_Conversion.Textures.BC;

internal static class HdrCube {
    public static byte[] Decode(byte[] packed,int size) {
        var faceBytes=((size+3)/4)*((size+3)/4)*16;
        if(size<1||size>2048||packed.Length<faceBytes*6)throw new InvalidDataException("Invalid BC6H cube size");
        var output=new byte[size*size*6*8];Span<ulong> block=stackalloc ulong[16];
        for(int face=0;face<6;face++)for(int y=0;y<size;y+=4)for(int x=0;x<size;x+=4) {
            int input=face*faceBytes+((y/4)*((size+3)/4)+x/4)*16;
            BCDecoder.DecodeBC6HBlock(BinaryPrimitives.ReadUInt64LittleEndian(packed.AsSpan(input)),BinaryPrimitives.ReadUInt64LittleEndian(packed.AsSpan(input+8)),block);
            for(int py=0;py<4&&y+py<size;py++)for(int px=0;px<4&&x+px<size;px++) {
                var pixel=block[py*4+px];var offset=(face*size*size+(y+py)*size+x+px)*8;
                BinaryPrimitives.WriteUInt64LittleEndian(output.AsSpan(offset),pixel);
            }
        }
        for(int i=0;i<output.Length;i+=2)if(!Half.IsFinite(BitConverter.UInt16BitsToHalf(BinaryPrimitives.ReadUInt16LittleEndian(output.AsSpan(i)))))
            throw new InvalidDataException("Source cube contains nonfinite HDR values");
        return output;
    }
    public static void WriteDds(string file,byte[] rgba,int size) {
        WriteDds(file,new[]{rgba},size);
    }
    static void WriteDds(string file,IReadOnlyList<byte[]> mips,int size) {
        Directory.CreateDirectory(Path.GetDirectoryName(file)!);
        using var writer=new BinaryWriter(File.Create(file));
        writer.Write(new byte[]{68,68,83,32});writer.Write(124);writer.Write(mips.Count>1?0x2100f:0x100f);writer.Write(size);writer.Write(size);writer.Write(size*8);writer.Write(0);writer.Write(mips.Count);writer.Write(new byte[44]);
        foreach(var v in new[]{32,4,0x30315844,0,0,0,0,0,mips.Count>1?0x401008:0x1008,0xfe00,0,0,0,10,3,4,1,0})writer.Write(v);
        // UE's cooked block stream is mip-major; DDS stores all mips of one
        // face before the next face. Preserve the original filtered levels.
        for(int face=0;face<6;face++)foreach(var mip in mips)writer.Write(mip,face*(mip.Length/6),mip.Length/6);
    }
    static int MipBytes(int size,int blockBytes) {
        int total=0;do{total+=((size+3)/4)*((size+3)/4)*blockBytes;size/=2;}while(size>0);
        return total*6;
    }
    public static void ExportLegacy(string output,ISet<string>? activePackages=null) {
        var rows=new List<object>();var failures=new List<object>();
        var assets=Path.Combine(output,"assets");
        if(Directory.Exists(assets))foreach(var file in Directory.EnumerateFiles(assets,"*Reflection.uexp",SearchOption.AllDirectories))try {
            var package=Path.GetRelativePath(assets,file).Replace('\\','/');package=package[..^5];
            if(activePackages is not null&&!activePackages.Contains(package))continue;
            var bytes=File.ReadAllBytes(file);using var reader=new BinaryReader(new MemoryStream(bytes));
            if(bytes.Length<22||BitConverter.ToUInt32(bytes,bytes.Length-4)!=0x9e2a83c1||bytes[12]!=1||bytes[13]!=0)
                throw new InvalidDataException("Unrecognized LocalReflectionGroupBake version");
            reader.BaseStream.Position=14;int count=reader.ReadInt32();
            if(count<1||count>4096)throw new InvalidDataException("Invalid reflection record count");
            var pending=new List<object>();
            for(int i=0;i<count;i++) {
                var guid=string.Concat(Enumerable.Range(0,4).Select(_=>reader.ReadUInt32().ToString("x8")));
                int size=reader.ReadInt32();float average=reader.ReadSingle(),brightness=reader.ReadSingle();int flags=reader.ReadInt32();
                if(size<4||size>2048||(size&(size-1))!=0||!float.IsFinite(average)||!float.IsFinite(brightness))throw new InvalidDataException("Invalid reflection header");
                var coefficients=Enumerable.Range(0,36).Select(_=>reader.ReadSingle()).ToArray();
                if(coefficients.Any(v=>!float.IsFinite(v)))throw new InvalidDataException("Invalid source coefficients");
                var extra=reader.ReadBytes(20);
                int length=reader.ReadInt32();if(length!=MipBytes(size,16))throw new InvalidDataException("BC6H mip layout mismatch");
                var color=reader.ReadBytes(length);if(color.Length!=length)throw new EndOfStreamException();
                int visibilityLength=reader.ReadInt32();if(visibilityLength!=MipBytes(size,8))throw new InvalidDataException("BC4 visibility mip layout mismatch");
                if(reader.ReadBytes(visibilityLength).Length!=visibilityLength)throw new EndOfStreamException();
                var decoded=Decode(color,size);
                var mips=new List<byte[]>{decoded};int inputOffset=((size+3)/4)*((size+3)/4)*16*6;
                for(int dimension=size/2;dimension>=1;dimension/=2) {
                    int blockLength=((dimension+3)/4)*((dimension+3)/4)*16*6;
                    mips.Add(Decode(color.AsSpan(inputOffset,blockLength).ToArray(),dimension));inputOffset+=blockLength;
                }
                double luminance=0,totalWeight=0;
                for(int pixel=0;pixel<decoded.Length;pixel+=8) {
                    double Channel(int channel)=>(double)BitConverter.UInt16BitsToHalf(BinaryPrimitives.ReadUInt16LittleEndian(decoded.AsSpan(pixel+channel*2)));
                    int index=(pixel/8)%(size*size);
                    double u=(index%size+.5)*2/size-1,v=(index/size+.5)*2/size-1;
                    double weight=1/Math.Pow(1+u*u+v*v,1.5);
                    luminance+=(Channel(0)*.2126+Channel(1)*.7152+Channel(2)*.0722)*weight;totalWeight+=weight;
                }
                luminance/=totalWeight;
                var identity=Convert.ToHexStringLower(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(package)))[..12];
                var relative="environment/reflection_"+guid+"_"+identity+".dds";
                WriteDds(Path.Combine(output,relative),mips,size);
                pending.Add(new{guid,size,average_brightness=average,brightness,flags,raw_coefficients=coefficients,
                    source=Path.GetRelativePath(output,file).Replace('\\','/'),source_sha256=Convert.ToHexStringLower(SHA256.HashData(bytes)),
                    texture=relative,format="RGBA16F",source_format="BC6H",mip_count=mips.Count,decoded_mean_luminance=luminance,
                    native_intensity_scale=luminance>0?average/luminance:1,
                    face_order="+X,-X,+Y,-Y,+Z,-Z",mip_layout="mip-major"});
            }
            if(reader.BaseStream.Position!=bytes.Length-4)throw new InvalidDataException("Unexpected reflection trailing data");
            rows.AddRange(pending);
        }catch(Exception e)when(!EnvironmentState.IsResourceFailure(e)){failures.Add(new{source=file,error=e.GetBaseException().Message});}
        File.WriteAllText(Path.Combine(output,"reflection-cubemaps.json"),JsonSerializer.Serialize(new{schema=1,captures=rows,failures},new JsonSerializerOptions{WriteIndented=true}));
        Console.WriteLine($"[state] decoded {rows.Count} source HDR reflection cubes; {failures.Count} unsupported layouts");
    }
}
