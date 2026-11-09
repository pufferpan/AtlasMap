using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Readers;

namespace Dfmap;

public static class MeshSections
{
    public sealed record Table(int Offset, FStaticMeshSection[] Sections);

    public static Table Find(IFileProvider provider, MeshData mesh)
    {
        if(mesh.Materials.Count==0 || mesh.Indices.Length==0) return null;
        var (package,_)=MeshCache.SplitObjectPath(mesh.Path);
        if(!provider.TryGetGameFile(package+".uexp",out var file)) return null;
        var bytes=file.Read();
        using var archive=new FByteArchive(mesh.Path,bytes,provider.Versions);
        var valid=new List<Table>();
        for(var offset=0;offset+28<bytes.Length;offset++)
        {
            var count=BitConverter.ToInt32(bytes,offset);
            if(count<1 || count>256 || count>mesh.TriangleCount) continue;
            var material=BitConverter.ToInt32(bytes,offset+4);
            var first=BitConverter.ToInt32(bytes,offset+8);
            var triangles=BitConverter.ToInt32(bytes,offset+12);
            var min=BitConverter.ToInt32(bytes,offset+16);
            var max=BitConverter.ToInt32(bytes,offset+20);
            if(material<0 || material>=mesh.Materials.Count || first!=0 || triangles<1
                || triangles>mesh.TriangleCount || min<0 || max<min || max>=mesh.VertexCount) continue;
            try
            {
                archive.Position=offset+4;
                var sections=new FStaticMeshSection[count];
                var next=0;
                var ok=true;
                for(var i=0;i<count;i++)
                {
                    var section=new FStaticMeshSection(archive);
                    sections[i]=section;
                    var end=(long)section.FirstIndex+section.NumTriangles*3L;
                    if(section.MaterialIndex<0 || section.MaterialIndex>=mesh.Materials.Count
                        || section.FirstIndex!=next || section.FirstIndex%3!=0 || section.NumTriangles<0
                        || end>mesh.Indices.Length || section.MinVertexIndex<0
                        || section.MaxVertexIndex<section.MinVertexIndex || section.MaxVertexIndex>=mesh.VertexCount)
                    { ok=false;break; }
                    for(var k=section.FirstIndex;k<end;k++)
                        if(mesh.Indices[k]<section.MinVertexIndex || mesh.Indices[k]>section.MaxVertexIndex)
                        {ok=false;break;}
                    if(!ok) break;
                    next=(int)end;
                }
                if(ok && next==mesh.Indices.Length) valid.Add(new Table(offset,sections));
            }
            catch { /* only accept a fully parsed and self-consistent table */ }
        }
        if(valid.Count==0) return null;
        var signatures=valid.GroupBy(t=>string.Join(";",t.Sections.Select(s=>$"{s.FirstIndex},{s.NumTriangles},{s.MaterialIndex}"))).ToList();
        return signatures.Count==1 ? signatures[0].First() : null;
    }

    public static int[] FaceMaterials(MeshData mesh, IEnumerable<FStaticMeshSection> sections)
    {
        var result=new int[mesh.TriangleCount];
        foreach(var section in sections)
        {
            if(section.FirstIndex%3!=0 || section.FirstIndex<0 || section.NumTriangles<0
                || section.FirstIndex/3L+section.NumTriangles>result.Length)
                throw new InvalidDataException("Section extends beyond the render index buffer");
            Array.Fill(result,section.MaterialIndex,section.FirstIndex/3,section.NumTriangles);
        }
        return result;
    }
}
