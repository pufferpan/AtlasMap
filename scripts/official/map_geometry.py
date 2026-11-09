"""Source-derived UE FBX topology accounting; no triangle-count tolerance."""
REVISION = 'ue_float32_cm_v1'


def audit_triangles(vertices, indices, slots):
    import numpy as np
    # FbxStaticMeshImport.cpp uses FVector3f centimetres and the cross product
    # (P1-P2) x (P0-P2), even with remove_degenerates disabled.
    points = (np.asarray(vertices, dtype=np.float64) * [100., -100., 100.]).astype(np.float32)
    triangles = points[np.asarray(indices).reshape(-1, 3)]
    cross = np.cross(triangles[:, 1] - triangles[:, 2], triangles[:, 0] - triangles[:, 2])
    removed = np.all(cross == 0, axis=1)
    if not np.isfinite(cross).all():
        raise ValueError('Non-finite source geometry')
    slots = np.asarray(slots)
    return dict(ue_topology_revision=REVISION, ue_degenerate_triangles=int(removed.sum()),
                ue_degenerate_face_slot_counts={str(int(i)): int(np.count_nonzero(removed & (slots == i)))
                                               for i in np.unique(slots[removed])})


def expected_triangles(row):
    removed = row.get('ue_degenerate_triangles', row.get('zero_area_triangles', row.get('repeated_index_triangles', 0)))
    total = row['triangles']
    if not isinstance(removed, int) or not 0 <= removed <= total:
        raise ValueError('Invalid source degenerate triangle count')
    return total - removed


def expected_face_slots(row):
    removed = row.get('ue_degenerate_face_slot_counts', row.get('zero_area_face_slot_counts', {}))
    result = {k: v - removed.get(k, 0) for k, v in row['face_slot_counts'].items()}
    if any(v < 0 for v in result.values()):
        raise ValueError('Invalid source degenerate face-slot counts')
    return {k: v for k, v in result.items() if v}
