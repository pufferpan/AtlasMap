using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using CUE4Parse.FileProvider;
using Dfmap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class AttributeBundle
{
    public static void Build(IFileProvider provider,string output,string input)
    {
        var cache=new MeshCache(provider);
        var rows=new List<object>();
        foreach(var item in JArray.Parse(File.ReadAllText(input)))
        {
            var path=item.Type==JTokenType.String?item.Value<string>():item.Value<string>("asset");
            var mesh=cache.Get(path);
            if(mesh is null){Console.WriteLine($"undecodable {path}");continue;}
            var stem=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(path))).ToLowerInvariant()[..20];
            var channels=mesh.UvChannels??new[]{mesh.Uvs};
            var files=new List<string>();
            foreach(var channel in channels)
            {
                var filename=stem+"_uv"+files.Count+".f32";
                File.WriteAllBytes(Path.Combine(output,filename),MemoryMarshal.AsBytes(channel.AsSpan()).ToArray());
                files.Add(filename);
            }
            string colorFile=null;
            if(mesh.Colors?.Length==mesh.VertexCount*4)
            {
                colorFile=stem+"_rgba.u8";
                File.WriteAllBytes(Path.Combine(output,colorFile),mesh.Colors);
            }
            rows.Add(new{asset=path,vertices=mesh.VertexCount,triangles=mesh.TriangleCount,
                index_sha256=Convert.ToHexString(SHA256.HashData(MemoryMarshal.AsBytes(mesh.Indices.AsSpan()))).ToLowerInvariant(),
                color_file=colorFile,color_buffer_state=mesh.ColorBufferState,uv_files=files,uv_ranges=channels.Select(c=>new{minU=c.Where((_,i)=>i%2==0).Min(),maxU=c.Where((_,i)=>i%2==0).Max(),minV=c.Where((_,i)=>i%2==1).Min(),maxV=c.Where((_,i)=>i%2==1).Max()})});
        }
        File.WriteAllText(Path.Combine(output,"attributes.json"),JsonConvert.SerializeObject(rows,Formatting.Indented));
        Console.WriteLine($"Attributes exported: {rows.Count}");
    }
}
