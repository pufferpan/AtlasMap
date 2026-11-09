using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using CUE4Parse.FileProvider;
using Dfmap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class RepairBundle
{
    public static void Build(IFileProvider provider,string output,string snapshotFile,string additionsFile)
    {
        Directory.CreateDirectory(output);
        Directory.CreateDirectory(Path.Combine(output,"face_materials"));
        CUE4Parse_Conversion.Textures.BC.DetexHelper.LoadDll(Path.GetFullPath("Detex.dll"));
        CUE4Parse_Conversion.Textures.BC.DetexHelper.Initialize(Path.GetFullPath("Detex.dll"));
        CUE4Parse.Compression.ZlibHelper.Initialize(Path.GetFullPath("zlib-ng2.dll"));
        var snapshot=JObject.Parse(File.ReadAllText(snapshotFile));
        var cache=new MeshCache(provider);
        var meshReports=new List<object>();
        var skipped=new List<object>();
        var materialPaths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var sceneMeshes=(JArray)snapshot["meshes"]!;
        var number=0;
        foreach(var item in sceneMeshes)
        {
            var asset=item.Value<string>("asset");
            if(string.IsNullOrEmpty(asset)||asset.Contains('#'))continue;
            var mesh=cache.Get(asset);
            if(mesh is null){skipped.Add(new {asset,reason="mesh not decodable"});continue;}
            var nativeHash=Convert.ToHexString(SHA256.HashData(MemoryMarshal.AsBytes(mesh.Indices.AsSpan()))).ToLowerInvariant();
            if(mesh.VertexCount!=item.Value<int>("vertices")||mesh.TriangleCount!=item.Value<int>("triangles")||nativeHash!=item.Value<string>("index_sha256"))
            {skipped.Add(new {asset,reason="live topology differs; retained existing materials"});continue;}
            var faces=mesh.FaceMaterial;
            if(faces is null && mesh.Materials.Count==1)faces=new int[mesh.TriangleCount];
            if(faces is null || mesh.Materials.Count==0)
            {skipped.Add(new {asset,reason="no verified render-section table"});continue;}
            var used=faces.Distinct().Order().ToArray();
            if(used.Any(i=>i<0||i>=mesh.Materials.Count))
            {skipped.Add(new {asset,reason="section references an absent material slot"});continue;}
            foreach(var slot in used)if(!string.IsNullOrEmpty(mesh.Materials[slot]))materialPaths.Add(mesh.Materials[slot]);
            var stem=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(asset))).ToLowerInvariant()[..20];
            var faceFile="face_materials/"+stem+".u16";
            File.WriteAllBytes(Path.Combine(output,faceFile),MemoryMarshal.AsBytes(faces.Select(i=>(ushort)i).ToArray().AsSpan()).ToArray());
            meshReports.Add(new {asset,data_name=item.Value<string>("data_name"),vertex_count=mesh.VertexCount,triangle_count=mesh.TriangleCount,
                index_sha256=nativeHash,materials=mesh.Materials,used_source_slots=used,face_material_file=faceFile});
            if(++number%100==0)Console.WriteLine($"verified face-material tables {number}/{sceneMeshes.Count}");
        }

        var additions=JArray.Parse(File.ReadAllText(additionsFile));
        var added=new List<object>();
        var writer=new GlbWriter();
        foreach(var token in additions)
        {
            var instance=token.ToObject<MeshInstance>();
            var mesh=cache.Get(instance!.Mesh);
            if(mesh is null){skipped.Add(new {asset=instance.Mesh,reason="addition mesh not decodable"});continue;}
            foreach(var material in mesh.Materials.Where(x=>!string.IsNullOrEmpty(x)))materialPaths.Add(material);
            var node="COMMON_MAP_ADDITION_"+added.Count.ToString("00000");
            writer.AddInstance(writer.AddMesh(mesh),instance.Loc,instance.Rot,instance.Scale,node,instance.MatrixUE);
            added.Add(new {node_name=node,asset=instance.Mesh,source_level=token.Value<string>("source_level"),instance.Loc,instance.MatrixUE});
        }
        var textures=new TextureCache(provider,output,"textures",512);
        var library=new Dictionary<string,object>(StringComparer.OrdinalIgnoreCase);
        var index=0;
        foreach(var path in materialPaths)
        {
            var info=textures.Material(path);
            if(info is null)continue;
            var color=textures.Texture(info.BaseColor);
            var normal=textures.Texture(info.Normal);
            var mra=textures.Texture(info.Mra);
            library[path]=new {path,base_color=color?.RelativePath,normal=normal?.RelativePath,mra=mra?.RelativePath,tint=info.Tint,
                original_base_color=info.BaseColor,original_normal=info.Normal,original_mra=info.Mra};
            writer.MaterialTextureFiles[path]=(color?.RelativePath,normal?.RelativePath,mra?.RelativePath,info.Tint);
            if(++index%100==0)Console.WriteLine($"material library {index}/{materialPaths.Count}; decoded {textures.DecodedCount}");
        }
        writer.Write(Path.Combine(output,"common_additions.glb"),"Iceland_Common_Static_Additions");
        var summary=new {checked_live_meshes=sceneMeshes.Count,verified_meshes=meshReports.Count,
            repaired_multimaterial_meshes=meshReports.Count(r=>JObject.FromObject(r)["used_source_slots"]!.Count()>1),
            additions=added.Count,materials=library.Count,decoded_images=textures.DecodedCount,
            texture_misses=textures.MissReasons,skipped_count=skipped.Count};
        File.WriteAllText(Path.Combine(output,"repair_bundle.json"),JsonConvert.SerializeObject(new {summary,meshes=meshReports,materials=library,additions=added,skipped},Formatting.Indented));
        Console.WriteLine(JsonConvert.SerializeObject(summary,Formatting.Indented));
    }
}
