using CUE4Parse.Compression;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse_Conversion.Textures.BC;
using Dfmap;
using Newtonsoft.Json;

internal static class RuntimeTextureLayers
{
    public static void Build(IFileProvider provider,string output,string path,int mip)
    {
        DetexHelper.LoadDll(Path.GetFullPath("Detex.dll"));
        DetexHelper.Initialize(Path.GetFullPath("Detex.dll"));
        ZlibHelper.Initialize(Path.GetFullPath("zlib-ng2.dll"));
        var texture=provider.LoadPackageObject<UTexture2D>(path);
        if(!VirtualTextureCompat.Repair(texture,out var reason))throw new InvalidDataException(reason);
        var vt=texture.PlatformData.VTData;
        var offsets=vt.GetTileOffsetData(mip);
        var tile=(int)vt.TileSize;var border=(int)vt.TileBorderSize;var physical=(int)vt.GetPhysicalTileSize();
        var width=(int)offsets.Width*tile;var height=(int)offsets.Height*tile;
        if(offsets.MaxAddress>1 && vt.IsLegacyData())
        {var divisor=1<<mip;width/=divisor;height/=divisor;}
        if(width>8192||height>8192)throw new InvalidDataException("Use a bounded RVT mip");
        var rows=new List<object>();
        for(uint layer=0;layer<vt.NumLayers;layer++)
        {
            if(vt.LayerTypes[layer].ToString()!="PF_DXT5")throw new NotSupportedException("Unexpected layer format "+vt.LayerTypes[layer]);
            var packed=new byte[((physical+3)/4)*((physical+3)/4)*16];
            var rgba=new byte[width*height*4];var tiles=0;
            for(uint address=0;address<offsets.MaxAddress;address++)
            {
                if(!vt.IsValidAddress(mip,address))continue;
                var x=Morton(address)*tile;var y=Morton(address>>1)*tile;
                if(x+tile>width||y+tile>height)throw new InvalidDataException("RVT tile outside output bounds");
                var (chunkIndex,start,length)=vt.GetTileData(mip,address,layer);
                var chunk=vt.Chunks[chunkIndex];var source=chunk.BulkData.Data;
                if(chunk.CodecType[layer]==EVirtualTextureCodec.ZippedGPU_DEPRECATED)
                    CUE4Parse.Compression.Compression.Decompress(source,(int)start,(int)length,packed,0,packed.Length,CompressionMethod.Zlib);
                else if(chunk.CodecType[layer]==EVirtualTextureCodec.RawGPU)
                    Array.Copy(source,start,packed,0,packed.Length);
                else throw new NotSupportedException("RVT codec "+chunk.CodecType[layer]);
                var pixels=BCDecoder.BC3(packed,physical,physical,1);
                for(var row=0;row<tile;row++)
                    Array.Copy(pixels,((row+border)*physical+border)*4,rgba,((y+row)*width+x)*4,tile*4);
                tiles++;
            }
            var file=$"rvt_layer{layer}_mip{mip}.png";
            MapImage.WritePng(Path.Combine(output,file),rgba,width,height);
            rows.Add(new{layer,file,width,height,tiles,format=vt.LayerTypes[layer].ToString()});
        }
        File.WriteAllText(Path.Combine(output,"layers.json"),JsonConvert.SerializeObject(new{source=path,mip,layers=rows},Formatting.Indented));
        Console.WriteLine($"RVT: {rows.Count} separate layers, {width}x{height}");
    }
    private static int Morton(uint value)
    {
        value&=0x55555555;value=(value^(value>>1))&0x33333333;value=(value^(value>>2))&0x0f0f0f0f;
        value=(value^(value>>4))&0x00ff00ff;value=(value^(value>>8))&0x0000ffff;return (int)value;
    }
}
