"""An explicit choice after an unsuccessful export, defaulting to keep."""
from PySide6.QtCore import Qt
from app.fluent_controls import ChoiceDialog,set_details


def cleanup_question(parent, plan, code):
    reason='导出已取消' if code==-2 else '导出失败'
    dialog=ChoiceDialog('清理导出残留',reason+'，是否删除本次导出的残留文件？',parent,
                        yes='删除残留文件',no='保留文件',warning=
        f'可清理 {len(plan.candidates):,} 个新增文件，约 {plan.size/1024**3:.2f} GB。\n'
        '已有文件和日志会保留；删除后需要重新导出。'
        + ('\n部分目录无法安全检查，将予以保留。' if plan.warnings else ''))
    dialog.setWindowFlag(Qt.WindowStaysOnTopHint,True)
    dialog.setWindowModality(Qt.ApplicationModal)
    # The main window is hidden and export windows are Qt.Tool windows. This
    # transient question must not quit the application when its answer closes it.
    dialog.setAttribute(Qt.WA_QuitOnClose,False)
    delete=dialog.yes_button
    delete.setEnabled(bool(plan.candidates))
    paths=list(plan.candidates)
    set_details(dialog,'\n'.join(str(p) for p in paths[:100])+
        (f'\n……共 {len(paths):,} 个文件' if len(paths)>100 else '')+
        ('\n'+'\n'.join(plan.warnings) if plan.warnings else ''))
    dialog.delete_residue_button=delete
    return dialog
