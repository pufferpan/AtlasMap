using CUE4Parse.FileProvider;
using Dfmap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class MaterialRefresh
{
    public static void Build(IFileProvider provider,string output,string input)
    {
        Directory.CreateDirectory(output);
        CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(Path.GetFullPath("Detex.dll"));
        CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(Path.GetFullPath("Detex.dll"));
        CUE4Parse.Compression.ZlibHelper.Initialize(Path.GetFullPath("zlib-ng2.dll"));
        var paths=JObject.Parse(File.ReadAllText(input)).Properties().Select(p=>p.Name).ToList();
        var cache=new TextureCache(provider,output,"textures",512);
        var materials=new Dictionary<string,object>();
        foreach(var path in paths)
        {
            var info=cache.Material(path);
            if(info is null)continue;
            var color=cache.Texture(info.BaseColor);
            var normal=cache.Texture(info.Normal);
            var mra=cache.Texture(info.Mra);
            var parameters=new Dictionary<string,object>();
            foreach(var parameter in info.TextureParameters)
            {
                var file=cache.Texture(parameter.Value);
                parameters[parameter.Key]=new {source=parameter.Value,file=file?.RelativePath};
            }
            materials[path]=new {path,info.MasterPath,info.Tint,info.ScalarParameters,info.VectorParameters,info.SwitchParameters,
                texture_parameters=parameters,base_color=color?.RelativePath,normal=normal?.RelativePath,mra=mra?.RelativePath,
                original_base_color=info.BaseColor,original_normal=info.Normal,original_mra=info.Mra};
            if(materials.Count%50==0)Console.WriteLine($"material refresh {materials.Count}/{paths.Count}: {cache.DecodedCount} images, {cache.Missed} misses");
        }
        var report=new {material_count=materials.Count,decoded_images=cache.DecodedCount,misses=cache.Missed,miss_reasons=cache.MissReasons,materials,failures=cache.Failures};
        File.WriteAllText(Path.Combine(output,"material_refresh.json"),JsonConvert.SerializeObject(report,Formatting.Indented));
        Console.WriteLine($"Finished {materials.Count} materials, {cache.DecodedCount} images, {cache.Missed} misses.");
        foreach(var reason in cache.MissReasons)Console.WriteLine($"{reason.Key}: {reason.Value}");
    }
}
