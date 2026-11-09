using Dfmap;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse_Conversion.Textures;
using Newtonsoft.Json;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Readers;

var root=@"E:\dfmap-tool-20260930\out\Iceland\audit\environment_query";
var cfg=JsonConvert.DeserializeObject<GameConfig>(File.ReadAllText(Path.Combine(root,"dfmap.json")));
DeltaForceTypes.Register();
ObjectTypeRegistry.RegisterClass("TextureCube",typeof(TraceCube));
var lib=@"E:\dfmap-tool-20260930\dfmap\bin\Release\net10.0";
CUE4Parse.Compression.OodleHelper.Initialize(Path.Combine(lib,"oodle-data-shared.dll"));
CUE4Parse.Compression.ZlibHelper.Initialize(Path.Combine(lib,"zlib-ng2.dll"));
CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(Path.Combine(lib,"Detex.dll"));
CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(Path.Combine(lib,"Detex.dll"));
using var provider=Mount.Create(cfg,AesKeySet.Load(cfg.KeyFile));
foreach(var path in args){
 var pkg=path.Split('.')[0];var name=pkg.Split('/').Last();
 var tex=provider.SafeLoadPackageObject<UTexture>(pkg,name);
 Console.WriteLine($"Texture {name}: {tex?.GetType().Name} platform={tex?.PlatformData?.PixelFormat} size={tex?.PlatformData?.SizeX}x{tex?.PlatformData?.SizeY}");
 if(tex==null)continue;
 var output=Path.Combine(root,"lighting",name);Directory.CreateDirectory(output);
 var rows=new List<object>();
 if(tex.Format==EPixelFormat.PF_BC6H){
  var mip=tex.GetMip(0);var raw=mip.BulkData.Data;File.WriteAllBytes(Path.Combine(output,"bc6_mip0.bin"),raw);
  Console.WriteLine($"BC6 raw={raw.Length} mip={mip.SizeX}x{mip.SizeY}x{mip.SizeZ}");
  for(int face=0;face<6;face++){
   var slice=raw.AsSpan(face*128*128,128*128).ToArray();
   var floats=new float[128*128*4];var block=new ulong[16];
   for(int by=0;by<32;by++)for(int bx=0;bx<32;bx++){
    var offset=(by*32+bx)*16;
    CUE4Parse_Conversion.Textures.BC.BCDecoder.DecodeBC6HBlock(BitConverter.ToUInt64(slice,offset),BitConverter.ToUInt64(slice,offset+8),block);
    for(int j=0;j<16;j++)for(int ch=0;ch<4;ch++)floats[((by*4+j/4)*128+bx*4+j%4)*4+ch]=(float)BitConverter.UInt16BitsToHalf((ushort)(block[j]>>(ch*16)));
   }
   var bytes=new byte[floats.Length*4];Buffer.BlockCopy(floats,0,bytes,0,bytes.Length);
   File.WriteAllBytes(Path.Combine(output,$"face{face}_float32_rgba.bin"),bytes);
  }
 }
 for(var layer=0;layer<((tex.PlatformData.GetNumSlices()&255)==6?6:1);layer++){
  try{
   var decoded=tex.DecodeMip(0,ETexturePlatform.DesktopMobile,layer);
   File.WriteAllBytes(Path.Combine(output,$"layer{layer}.bin"),decoded.Data);
   rows.Add(new {layer,width=decoded.Width,height=decoded.Height,format=decoded.PixelFormat.ToString(),bytes=decoded.Data.Length});
   Console.WriteLine(JsonConvert.SerializeObject(rows.Last()));
  }catch(Exception ex){Console.WriteLine($"Decode {layer}: {ex}");}
 }
 File.WriteAllText(Path.Combine(output,"metadata.json"),JsonConvert.SerializeObject(rows,Formatting.Indented));
}

public class TraceCube:UTexture{
 public override void Deserialize(FAssetArchive ar,long validPos){
  try{base.Deserialize(ar,validPos);}catch(Exception ex){Console.WriteLine($"Cube base failure {ex} pos={ar.Position}");}
  Console.WriteLine($"Cube parse pos={ar.Position} absolute={ar.AbsolutePosition} valid={validPos} remain={validPos-ar.Position}");
  var start=ar.Position;var raw=ar.ReadBytes((int)(validPos-start));Console.WriteLine(Convert.ToHexString(raw[..Math.Min(120,raw.Length)]));ar.Position=start;
  var strip=ar.ReadBytes(2);var cooked=ar.ReadBoolean();var fmt=ar.ReadFName();var skip=ar.Read<long>();Console.WriteLine($"Cube header cooked={cooked} fmt={fmt} skip={skip} pos={ar.Position}");
  var pd=new FTexturePlatformData();
  void Field(string key,object val)=>typeof(FTexturePlatformData).GetField(key).SetValue(pd,val);
  Field("SizeX",ar.Read<int>());Field("SizeY",ar.Read<int>());Field("PackedData",ar.Read<uint>());
  Field("PixelFormat",ar.ReadFString());Field("FirstMipToSerialize",ar.Read<int>());
  var count=ar.Read<int>();Console.WriteLine($"Manual header {pd.SizeX}x{pd.SizeY} packed={pd.PackedData:X8} fmt={pd.PixelFormat} count={count}");
  pd.Mips=new FTexture2DMipMap[count];for(int i=0;i<count;i++)pd.Mips[i]=new FTexture2DMipMap(ar,true);
  Console.WriteLine($"Manual cube consumed={ar.AbsolutePosition} expectedskip={skip} firstmip={pd.Mips[0].SizeX}x{pd.Mips[0].SizeY}");
  typeof(UTexture).GetProperty("PlatformData").SetValue(this,pd);
  Format=Enum.Parse<EPixelFormat>(fmt.Text);
 }
}
