using System.Text.RegularExpressions;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Texture;
using Dfmap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class GroundExport
{
    public static void Build(IFileProvider provider,string output,string diagnostics)
    {
        Directory.CreateDirectory(output);
        Directory.CreateDirectory(Path.Combine(output,"weightmaps"));
        CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(Path.GetFullPath("Detex.dll"));
        CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(Path.GetFullPath("Detex.dll"));
        CUE4Parse.Compression.ZlibHelper.Initialize(Path.GetFullPath("zlib-ng2.dll"));
        var array=JArray.Parse(File.ReadAllText(Path.Combine(diagnostics,"ground_dynamic_array.json")))[0]["value"]!["Properties"]!;
        var landscape=JArray.Parse(File.ReadAllText(Path.Combine(Directory.GetParent(diagnostics)!.FullName,"diagnostics/landscape_cd_lod.json")));
        var dta=landscape.First(x=>x.Value<string>("type")=="DTAComponent")["value"]!["Properties"]!;
        var actor=landscape.First(x=>x.Value<string>("type")=="ClipmapActor")["value"]!["Properties"]!;
        var textures=new TextureCache(provider,output,"layers",1024);
        var layers=new List<object>();
        var index=0;
        foreach(var reference in array["TextureArray"]!)
        {
            var path=reference.Value<string>("AssetPathName")!.Replace("/Game/","DeltaForce/Content/");
            var file=textures.Texture(path);
            if(file is null)throw new InvalidDataException("Ground layer unavailable: "+path);
            var parameters=dta["LayerParameters"]![index];
            var packed=parameters.Value<uint>("TextureArrayIndexAndTillingStarEnd");
            if((packed>>16)!=index)throw new InvalidDataException("Terrain layer ordering mismatch");
            layers.Add(new {index,source=path,file=file.RelativePath,tiling=parameters.Value<float>("TillingParameter"),parameters});
            index++;
        }
        var pattern=new Regex(@"/Mip0_x(?<x>\d+)_y(?<y>\d+)\.uasset$",RegexOptions.IgnoreCase);
        var prefix="DeltaForce/Content/Maps/BuildMaps_HD/Iceland/Runtime/LandscapeCDLOD/WeightmapClipmap/";
        var pages=new List<object>();
        foreach(var path in provider.Files.Keys.Where(x=>x.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)&&pattern.IsMatch(x)).Order())
        {
            var match=pattern.Match(path);
            var texture=provider.LoadPackageObject<UTexture2D>(path[..^7]);
            var mip=texture.GetFirstMip();
            var raw=mip.BulkData.Data;
            if(texture.Format.ToString()!="PF_G16"||raw is null||raw.Length!=mip.SizeX*mip.SizeY*2)
                throw new InvalidDataException($"Unexpected weightmap format {path}: {texture.Format} {mip.SizeX}x{mip.SizeY} {raw?.Length}");
            var filename="weightmaps/"+Path.GetFileNameWithoutExtension(path)+".u16";
            File.WriteAllBytes(Path.Combine(output,filename),raw);
            pages.Add(new {x=int.Parse(match.Groups["x"].Value),y=int.Parse(match.Groups["y"].Value),width=mip.SizeX,height=mip.SizeY,file=filename,source=path});
        }
        File.WriteAllText(Path.Combine(output,"ground_sources.json"),JsonConvert.SerializeObject(new {layers,pages,actor,dta},Formatting.Indented));
        Console.WriteLine($"Ground exported: {layers.Count} albedo layers, {pages.Count} raw G16 weight pages");
    }
}
