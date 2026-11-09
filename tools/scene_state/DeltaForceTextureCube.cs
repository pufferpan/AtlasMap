using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Assets.Readers;

// DeltaForce's cooked cube platform payload follows the UObject texture
// properties directly. The generic cube reader leaves PlatformData empty for
// these assets, although the six faces are present in the package.
internal sealed class DeltaForceTextureCube : UTexture {
    public override void Deserialize(FAssetArchive ar,long validPos) {
        base.Deserialize(ar,validPos);
        if(validPos-ar.Position<18)throw new InvalidDataException("Truncated DeltaForce cube header");
        ar.ReadBytes(2); // serialized strip-data flags
        if(!ar.ReadBoolean())throw new InvalidDataException("DeltaForce cube is not cooked");
        var format=ar.ReadFName();
        var endOffset=ar.Read<long>();
        var data=new FTexturePlatformData();
        void Field(string name,object value) => typeof(FTexturePlatformData).GetField(name)!.SetValue(data,value);
        var width=ar.Read<int>();var height=ar.Read<int>();var packed=ar.Read<uint>();
        var pixelFormat=ar.ReadFString();var firstMip=ar.Read<int>();var count=ar.Read<int>();
        if(width<1||height!=width||width>16384||count<1||count>16)
            throw new InvalidDataException($"Unsupported DeltaForce cube header {width}x{height}, mips={count}");
        Field("SizeX",width);Field("SizeY",height);Field("PackedData",packed);
        Field("PixelFormat",pixelFormat);Field("FirstMipToSerialize",firstMip);
        data.Mips=new FTexture2DMipMap[count];
        for(int i=0;i<count;i++)data.Mips[i]=new FTexture2DMipMap(ar,true);
        if(ar.Position>validPos)throw new InvalidDataException("DeltaForce cube payload exceeds export");
        // Serialized skip offsets may be absolute within the package archive.
        // Preserve the bounded mip parser instead of seeking blindly to them.
        typeof(UTexture).GetProperty("PlatformData")!.SetValue(this,data);
        Format=Enum.Parse<EPixelFormat>(format.Text);
    }
}
