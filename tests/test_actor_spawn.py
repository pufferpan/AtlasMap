"""Actor creation must bypass editor viewport picking and keep full transforms."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from scripts.official.ue_actor_spawn import spawn_actor


class ActorSpawnTests(unittest.TestCase):
    def unreal(self):
        world=object();actor=object()
        system=Mock();system.get_editor_world.return_value=world
        api=SimpleNamespace(UnrealEditorSubsystem=object(), get_editor_subsystem=Mock(return_value=system),
            Transform=Mock(), GameplayStatics=Mock(),
            get_default_object=Mock(), SpawnActorScaleMethod=SimpleNamespace(MULTIPLY_WITH_ROOT=object()),
            SpawnActorCollisionHandlingMethod=SimpleNamespace(ALWAYS_SPAWN=object()))
        api.get_default_object.return_value.call_method.return_value=actor
        return api,world,actor

    def test_preserves_full_transform_without_editor_actor_placement(self):
        api,world,actor=self.unreal();transform=object();cls=object();location=object()
        self.assertIs(spawn_actor(api,cls,location,transform=transform),actor)
        api.get_editor_subsystem.assert_called_once_with(api.UnrealEditorSubsystem)
        calls=api.get_default_object.return_value.call_method.call_args_list
        self.assertEqual(calls[0].args,('BeginDeferredActorSpawnFromClass',))
        self.assertEqual(calls[0].kwargs['args'],(world,cls,transform,
            api.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN,None,api.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT))
        self.assertEqual(calls[1].args,('FinishSpawningActor',))
        self.assertEqual(calls[1].kwargs['args'],(actor,transform,api.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT))
        api.Transform.assert_not_called()

    def test_lights_keep_source_location_and_rotation(self):
        api,_,_=self.unreal();location=object();rotation=Mock()
        spawn_actor(api,object(),location,rotation)
        transform=api.Transform.return_value
        transform.set_editor_property.assert_any_call('translation',location)
        transform.set_editor_property.assert_any_call('rotation',rotation.quaternion.return_value)

    def test_failure_never_falls_back_to_the_viewport_placement_path(self):
        api,_,_=self.unreal()
        api.get_default_object.return_value.call_method.return_value=None
        with self.assertRaisesRegex(RuntimeError,'Cannot spawn actor directly'):
            spawn_actor(api,object(),object())
        self.assertEqual(api.get_default_object.return_value.call_method.call_count,1)
