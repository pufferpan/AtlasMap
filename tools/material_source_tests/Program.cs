using System.Reflection;
using System.Text.Json;

void Check(bool value,string name) {if(!value)throw new Exception(name);Console.WriteLine("PASS "+name);}
JsonDocument Child(string parent) => JsonDocument.Parse(JsonSerializer.Serialize(new[]{new {
    type="MaterialInstanceConstant",name="Child",value=new {Properties=new {
        Roughness=.3,Parent=new {ObjectPath=parent}}}}}));
foreach(var name in new[]{"lambert1","Material.001","None","DefaultMaterial","../bad","C:/project/material"}) {
    var result=MaterialSources.Read(name,_=>throw new Exception("Placeholder must not reach provider"));
    Check(result.status=="placeholder"&&result.chain.Count==0&&result.issues.Count==1,"placeholder "+name);
}
foreach(var name in new[]{"/Game/Props/Material.Material","DeltaForce/Content/Props/Material.Material","Engine/Content/Materials/Default","/Plugin/Materials/Example"})
    Check(MaterialSources.IsPackageReference(name),"package mount "+name);
var calls=new List<string>();
var inherited=MaterialSources.Read("/Game/Child.Child",path=> {
    calls.Add(path);
    if(path=="/Game/Child")return Child("/Game/Parent.Parent");
    return JsonDocument.Parse("[{\"type\":\"Material\",\"value\":{\"Properties\":{\"BlendMode\":\"BLEND_Translucent\"}}}]");
});
Check(inherited.status=="complete"&&inherited.chain.Count==2&&calls.SequenceEqual(new[]{"/Game/Child","/Game/Parent"}),"native inheritance still resolves");
Check(inherited.chain[1].GetProperty("value").GetProperty("Properties").GetProperty("BlendMode").GetString()=="BLEND_Translucent","chain survives disposed documents");
var missing=MaterialSources.Read("/Game/Missing.Missing",_=>throw new TargetInvocationException(new KeyNotFoundException("missing source")));
Check(missing.status=="missing_source"&&missing.chain.Count==0,"missing optional source is reported");
var partial=MaterialSources.Read("/Game/Child.Child",path=>path=="/Game/Child"?Child("/Game/Missing.Missing"):throw new KeyNotFoundException("missing parent"));
Check(partial.status=="missing_parent"&&partial.chain.Count==1&&partial.chain[0].GetProperty("value").GetProperty("Properties").GetProperty("Roughness").GetDouble()==.3,"missing parent preserves child properties");
var cycle=MaterialSources.Read("/Game/Child.Child",_=>Child("/Game/Child.Child"));
Check(cycle.status=="parent_cycle"&&cycle.chain.Count==1,"cyclic parent does not loop");
var unreadable=MaterialSources.Read("/Game/Child.Child",_=>JsonDocument.Parse("[{\"error\":\"unreadable export\"}]"));
Check(unreadable.status=="no_material_export","unreadable native shader preserves fallback");
foreach(var error in new Exception[]{new IOException("disk full"),new OutOfMemoryException(),new JsonException("corrupt JSON")}) {
    try {MaterialSources.Read("/Game/Child.Child",_=>throw error);throw new Exception("Resource/corruption error was swallowed");}
    catch(Exception actual)when(ReferenceEquals(actual,error)) {Check(true,"fatal error propagates: "+error.GetType().Name);}
}
