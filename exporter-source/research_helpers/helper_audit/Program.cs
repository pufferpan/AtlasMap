using Dfmap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using CUE4Parse.UE4.Assets.Exports.Component;

var root=@"E:\dfmap-tool-20260930\out\Iceland\collision_rebuild\20261031";
var cfg=JsonConvert.DeserializeObject<GameConfig>(File.ReadAllText(@"E:\dfmap-tool-20260930\out\Iceland\audit\environment_query\dfmap.json"));
DeltaForceTypes.Register();
var lib=@"E:\dfmap-tool-20260930\dfmap\bin\Release\net10.0";
CUE4Parse.Compression.OodleHelper.Initialize(Path.Combine(lib,"oodle-data-shared.dll"));
CUE4Parse.Compression.ZlibHelper.Initialize(Path.Combine(lib,"zlib-ng2.dll"));
using var provider=Mount.Create(cfg,AesKeySet.Load(cfg.KeyFile));
var serializer=JsonSerializer.Create(Inspect.BuildJsonSettings(provider));
var rows=new List<object>();var errors=new List<object>();
foreach(var path in File.ReadAllLines(Path.Combine(root,"hidden_helper_levels.txt"))){
 try{
  var package=provider.LoadPackage(path);int found=0;
  foreach(var lazy in package.ExportsLazy){
   try{
    var obj=lazy.Value;
    if(obj?.ExportType!="StaticMeshComponent" || obj is not USceneComponent comp)continue;
    var json=JObject.FromObject(obj,serializer);var p=(JObject)json["Properties"];
    var mesh=(string)p?["StaticMesh"]?["ObjectPath"];
    var meshName=(string)p?["StaticMesh"]?["ObjectName"];
    if(mesh==null || !(meshName?.Contains("'BlockWallCube'")==true || meshName?.Contains("'Cube'")==true))continue;
    var transform=comp.GetAbsoluteTransform();
    rows.Add(new{source_level=path,component=obj.GetPathName(),name=obj.Name,mesh=mesh,mesh_name=meshName,
       loc=new[]{transform.Translation.X,transform.Translation.Y,transform.Translation.Z},
       hidden_in_game=p["bHiddenInGame"],visible=p["bVisible"],body=p["BodyInstance"],owner=json["Outer"]});found++;
   }catch(Exception ex){errors.Add(new{level=path,error=ex.Message});}
  }
  Console.WriteLine($"{Path.GetFileName(path)}: {found}");
 }catch(Exception ex){errors.Add(new{level=path,error=ex.Message});}
}
File.WriteAllText(Path.Combine(root,"native_helper_component_collision.json"),JsonConvert.SerializeObject(new{rows,errors},Formatting.Indented));
Console.WriteLine($"COMPLETE rows={rows.Count} errors={errors.Count}");
