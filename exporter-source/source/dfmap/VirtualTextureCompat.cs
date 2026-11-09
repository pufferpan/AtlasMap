using System.Reflection;
using System.Runtime.CompilerServices;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Assets.Readers;

namespace Dfmap;

/// <summary>
/// Repair legacy DF virtual-texture chunk descriptors when the package's
/// codec-offset width differs from the CUE4Parse build in use. Tile tables are
/// left untouched. Only an unambiguous, bounded descriptor layout is accepted.
/// </summary>
public static class VirtualTextureCompat
{
    public static bool Repair(UTexture2D texture,out string reason)
    {
        reason=null;
        var vt=texture.PlatformData?.VTData;
        if(vt is null||vt.Chunks is null||vt.Chunks.Length==0)return false;
        var maximum=Math.Max(16*1024*1024L,(long)vt.Width*vt.Height*Math.Max(1,vt.NumLayers)*16);
        bool Valid(FVirtualTextureDataChunk c)=>c.SizeInBytes>0 && c.SizeInBytes<=maximum
            && c.BulkData.Header.SizeOnDisk==c.SizeInBytes
            && c.BulkData.Header.ElementCount==c.SizeInBytes
            && c.CodecType.All(x=>(byte)x<=6);
        if(vt.Chunks.All(Valid))return true;
        FAssetArchive saved=null;
        for(var type=vt.Chunks[0].BulkData.GetType();type is not null;type=type.BaseType)
        {
            var flags=BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly;
            var field=type.GetField("_savedAr",flags)??type.GetField("<_savedAr>k__BackingField",flags);
            if(field?.GetValue(vt.Chunks[0].BulkData) is FAssetArchive ar){saved=ar;break;}
        }
        if(saved is null){reason="virtual texture source archive unavailable";return false;}
        var scan=(FAssetArchive)saved.Clone();
        if(scan.Length>64*1024*1024){reason="virtual texture metadata archive too large";return false;}
        scan.Position=0;
        var raw=scan.ReadBytes((int)scan.Length);
        var candidates=new List<(int Offset,int Width,FVirtualTextureDataChunk[] Chunks)>();
        for(var offset=0;offset+13<raw.Length;offset++)
        {
            if(BitConverter.ToInt32(raw,offset)!=vt.Chunks.Length
                ||BitConverter.ToUInt32(raw,offset+4)!=vt.Chunks[0].SizeInBytes
                ||BitConverter.ToUInt32(raw,offset+8)!=vt.Chunks[0].CodecPayloadSize
                ||raw[offset+12]!=(byte)vt.Chunks[0].CodecType[0])continue;
            foreach(var width in new[]{2,4})
            {
                try
                {
                    var archive=(FAssetArchive)saved.Clone();
                    archive.Position=offset+4;
                    var chunks=new FVirtualTextureDataChunk[vt.Chunks.Length];
                    for(var i=0;i<chunks.Length;i++)
                    {
                        var size=archive.Read<uint>();
                        var payloadSize=archive.Read<uint>();
                        if(size==0||size>maximum||payloadSize>size)throw new InvalidDataException();
                        var codecs=new EVirtualTextureCodec[vt.NumLayers];
                        var payloads=new uint[vt.NumLayers];
                        for(var layer=0;layer<vt.NumLayers;layer++)
                        {
                            codecs[layer]=(EVirtualTextureCodec)archive.Read<byte>();
                            payloads[layer]=width==2?archive.Read<ushort>():archive.Read<uint>();
                            if((byte)codecs[layer]>6||payloads[layer]>payloadSize)throw new InvalidDataException();
                        }
                        var bulk=new FByteBulkData(archive);
                        if(bulk.Header.SizeOnDisk!=size||bulk.Header.ElementCount!=size)throw new InvalidDataException();
                        var chunk=(FVirtualTextureDataChunk)RuntimeHelpers.GetUninitializedObject(typeof(FVirtualTextureDataChunk));
                        void Set(string name,object value)=>typeof(FVirtualTextureDataChunk).GetField(name)!.SetValue(chunk,value);
                        Set(nameof(chunk.SizeInBytes),size);
                        Set(nameof(chunk.CodecPayloadSize),payloadSize);
                        Set(nameof(chunk.CodecType),codecs);
                        Set(nameof(chunk.CodecPayloadOffset),payloads);
                        Set(nameof(chunk.BulkData),bulk);
                        chunks[i]=chunk;
                    }
                    if(chunks.All(Valid))candidates.Add((offset,width,chunks));
                }
                catch { /* reject an unbounded or structurally inconsistent layout */ }
            }
        }
        if(candidates.Count!=1){reason=$"virtual texture chunk layout candidates: {candidates.Count}";return false;}
        var candidate=candidates[0];
        for(var i=0;i<vt.Chunks.Length;i++)vt.Chunks[i]=candidate.Chunks[i];
        reason=$"repaired {vt.Chunks.Length} chunks with {candidate.Width}-byte codec offsets at {candidate.Offset}";
        return true;
    }
}
