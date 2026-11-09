"""Create saved editor actors without asking a NullRHI viewport for hit proxies."""


def spawn_actor(unreal, actor_class, location, rotation=None, transform=None):
    if transform is None:
        transform = unreal.Transform()
        transform.set_editor_property('translation', location)
        if rotation is not None:
            transform.set_editor_property('rotation', rotation.quaternion())
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    # These Blueprint-internal UFunctions have no generated Python methods in
    # UE 5.4. Object.call_method invokes their existing reflected entry points.
    api = unreal.get_default_object(unreal.GameplayStatics)
    scale_method = unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT
    actor = api.call_method('BeginDeferredActorSpawnFromClass', args=(
        world, actor_class, transform, unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN,
        None, scale_method))
    if actor is None:
        raise RuntimeError('Cannot spawn actor directly in the editor world: '+str(actor_class))
    result = api.call_method('FinishSpawningActor', args=(actor, transform, scale_method))
    if result is None:
        raise RuntimeError('Cannot finish editor actor creation: '+str(actor_class))
    return result
