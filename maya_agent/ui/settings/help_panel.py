"""Help tab content."""

from __future__ import annotations

from maya_agent import __app_name__, __version__
from maya_agent.i18n import t
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

def create_help_panel(parent=None):
    """Top-level help page (same visual language as settings sections)."""
    def _scroll_page():
        page = QtWidgets.QWidget()
        page.setObjectName("settingsPage")
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        root.setAlignment(QtCore.Qt.AlignTop)
        return scroll, root

    def _section(title: str, hint: str = ""):
        box = QtWidgets.QFrame()
        box.setObjectName("settingsSection")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QtWidgets.QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("settingsSectionTitle")
        head.addWidget(title_lbl)
        if hint:
            hint_lbl = QtWidgets.QLabel(hint)
            hint_lbl.setObjectName("settingsSectionHint")
            hint_lbl.setWordWrap(True)
            head.addWidget(hint_lbl)
        lay.addLayout(head)
        return box, lay

    def _add_help_lines(layout, lines, *, numbered: bool = False) -> None:
        for i, line in enumerate(lines, start=1):
            prefix = f"{i}.  " if numbered else "·  "
            row = QtWidgets.QLabel(f"{prefix}{line}")
            row.setObjectName("settingsHelpItem")
            row.setWordWrap(True)
            layout.addWidget(row)

    scroll, root = _scroll_page()

    intro = QtWidgets.QFrame()
    intro.setObjectName("settingsSection")
    intro_lay = QtWidgets.QVBoxLayout(intro)
    intro_lay.setContentsMargins(14, 14, 14, 14)
    intro_lay.setSpacing(8)

    title_row = QtWidgets.QHBoxLayout()
    title_row.setSpacing(10)
    title = QtWidgets.QLabel(__app_name__)
    title.setObjectName("settingsHelpTitle")
    ver = QtWidgets.QLabel(f"v{__version__}")
    ver.setObjectName("settingsHelpVersion")
    title_row.addWidget(title, 0)
    title_row.addWidget(ver, 0)
    title_row.addStretch(1)
    intro_lay.addLayout(title_row)

    blurb = QtWidgets.QLabel(t("help.blurb"))
    blurb.setObjectName("settingsHelpBody")
    blurb.setWordWrap(True)
    intro_lay.addWidget(blurb)
    root.addWidget(intro)

    quick, quick_lay = _section(t("help.quick.title"), t("help.quick.hint"))
    _add_help_lines(
        quick_lay,
        (
            t("help.quick.1"),
            t("help.quick.2"),
            t("help.quick.3"),
            t("help.quick.4"),
        ),
        numbered=True,
    )
    root.addWidget(quick)

    chat, chat_lay = _section(t("help.chat.title"), t("help.chat.hint"))
    _add_help_lines(
        chat_lay,
        (
            t("help.chat.1"),
            t("help.chat.2"),
            t("help.chat.3"),
            t("help.chat.4"),
            t("help.chat.5"),
            t("help.chat.6"),
            t("help.chat.7"),
            t("help.chat.8"),
            t("help.chat.9"),
        ),
    )
    root.addWidget(chat)

    settings, settings_lay = _section(
        t("help.settings.title"), t("help.settings.hint")
    )
    _add_help_lines(
        settings_lay,
        (
            t("help.settings.1"),
            t("help.settings.2"),
            t("help.settings.meshy"),
            t("help.settings.tripo"),
            t("help.settings.3"),
            t("help.settings.4"),
        ),
    )
    root.addWidget(settings)

    ui_help, ui_help_lay = _section(t("help.ui.title"), t("help.ui.hint"))
    _add_help_lines(
        ui_help_lay,
        (
            t("help.ui.1"),
            t("help.ui.2"),
            t("help.ui.3"),
        ),
    )
    root.addWidget(ui_help)

    tools, tools_lay = _section(t("help.tools.title"), t("help.tools.hint"))
    tool_groups = (
        (
            "场景 scene",
            "get_scene_info（含 bbox/相机裁剪/材质分布）、list_selection、select_objects、rename_object、batch_rename、"
            "create_group、delete_objects、parent_objects、duplicate_objects、clean_scene、"
            "set_frame_range、capture_viewport（show_only/display_mode/look_at）、"
            "capture_viewport_views（临时相机自动清理）、render_still（静帧展示图）",
        ),
        (
            "建模 modeling",
            "create_primitive（含 pipe/pyramid/helix 等）、create_primitives、arrange_objects（stack/align/grid/radial）、"
            "select_mesh_components（按法线/索引/边界选面边点）、extrude_faces、extrude_edges、bevel_edges、"
            "edit_mesh_topology、edit_mesh_normals、transform_components、boolean_meshes、combine_meshes、"
            "create_curve、mesh_from_curve、create_text_mesh、thicken_mesh、cleanup_mesh、"
            "get_mesh_stats、check_meshes",
        ),
        (
            "UV",
            "auto_unwrap_uv、layout_uv、check_uv_overlaps",
        ),
        (
            "绑骨 rigging",
            "原生：list_skeleton_templates、create_skeleton_*、create_skin_cage、"
            "bind_from_skin_cage、build_fk_ik_controls、auto_rig_character、"
            "list_skinned_meshes、extract_skinned_geometry 等",
        ),
        (
            "AdvancedSkeleton adv",
            "已安装 ADV 时自动启用：adv_rig_status、adv_auto_rig（一键）、"
            "adv_next_step（分步）、adv_import_fit_skeleton、adv_set_skin_meshes、"
            "adv_auto_place_fit、adv_build_rig、adv_bind_skin、adv_create_controller。"
            "路径在「设置」页的 AdvancedSkeleton 栏配置",
        ),
        (
            "动画 animation",
            "set_keyframe、delete_keyframes、bake_animation、playblast、copy_animation",
        ),
        (
            "材质 materials",
            "create_material（返回 shader+shading_group）、assign_material、describe_material_attrs、assign_texture、list_materials",
        ),
        (
            "灯光 lighting",
            "create_light、create_three_point_lighting、create_environment_light（天光/环境光）",
        ),
        (
            "导入导出 export",
            "export_fbx、import_fbx、export_obj、export_usd、export_abc、save_scene、open_scene",
        ),
        (
            "游戏管线 utilities",
            "set_transform、create_lod_group、create_collision_mesh、apply_game_naming、reset_transform",
        ),
        (
            "本地文件 files",
            "get_workspace_info、list_directory、path_info、read_text_file、write_text_file、"
            "copy_file、delete_path、list_chat_images、save_chat_images"
            "（工作区 maya_agent_files 与 MayaAgent 同级；对话附图自动落盘到 chat_images）",
        ),
        (
            "网络检索 web",
            "web_search、fetch_webpage、search_images、fetch_image、fetch_images"
            "（按需查文档/规范与参考图；fetch_image* 仅视觉模型可用）",
        ),
        (
            "Meshy AI meshy",
            "meshy_text_to_3d（preview→refine）、meshy_image_to_3d（可用 use_latest_chat_image）、"
            "meshy_multi_image_to_3d、meshy_retexture、meshy_remesh、meshy_convert、meshy_resize、"
            "meshy_uv_unwrap、meshy_rig、meshy_animate、meshy_list_animations、meshy_get_task、"
            "meshy_wait_task、meshy_download_model、meshy_import_to_maya、meshy_balance"
            "（需在设置中配置 Meshy API Key；导入优先 FBX）",
        ),
        (
            "Tripo AI tripo",
            "tripo_text_to_model、tripo_image_to_model、tripo_multiview_to_model、"
            "tripo_text_to_image、tripo_image_to_image、tripo_image_to_multiview、tripo_edit_multiview、"
            "tripo_texture、tripo_convert、tripo_mesh_segment、tripo_mesh_complete、tripo_mesh_decimate、"
            "tripo_rig_check、tripo_rig、tripo_retarget、tripo_list_animations、"
            "tripo_prepare_rig_export、tripo_apply_to_meshes、tripo_apply_animation、"
            "tripo_get_task、tripo_wait_task、tripo_list_tasks、tripo_upload_file、"
            "tripo_download、tripo_import_to_maya、tripo_balance、tripo_usage"
            "（需在设置中配置 Tripo API Key；导入优先 FBX）",
        ),
        (
            "脚本 scripting",
            "execute_python（atomic 默认回滚）、execute_mel、generate_python_snippet",
        ),
    )
    for cat, names in tool_groups:
        cat_lbl = QtWidgets.QLabel(cat)
        cat_lbl.setObjectName("settingsHelpCat")
        cat_lbl.setWordWrap(True)
        tools_lay.addWidget(cat_lbl)
        names_lbl = QtWidgets.QLabel(names)
        names_lbl.setObjectName("settingsHelpItem")
        names_lbl.setWordWrap(True)
        tools_lay.addWidget(names_lbl)
    note = QtWidgets.QLabel(
        "·  标记为危险的工具（删除、解绑、打开场景、执行脚本等）在开启「危险操作前确认」时会弹窗。"
    )
    note.setObjectName("settingsHelpItem")
    note.setWordWrap(True)
    tools_lay.addWidget(note)
    root.addWidget(tools)

    rules, rules_lay = _section(
        "使用约定与安全",
        "Agent 会遵循下列约束，请按此预期使用。",
    )
    _add_help_lines(
        rules_lay,
        (
            "所有操作默认在当前已打开场景中进行；除非你明确要求，否则不会新建空场景",
            "意图含糊、缺参数或多种方案时，会先用选项向你确认再动手",
            "删除物体、覆盖导出、执行任意脚本等危险操作会先确认",
            "优先使用已注册工具；复杂逻辑才用 execute_python / execute_mel",
            "修改应可撤销：请保持「自动 Undo 块」开启，便于一轮一次回退",
        ),
    )
    root.addWidget(rules)

    more, more_lay = _section(
        "菜单与重载",
        "安装后可从 Maya 菜单或工具架打开。",
    )
    _add_help_lines(
        more_lay,
        (
            "菜单「Maya Agent」：打开面板、重新加载、关于",
            "修改插件代码后可用「重新加载」刷新；依赖或安装路径变更建议重跑 install.bat 并重启 Maya",
            "API Key 也可通过环境变量配置（如 DEEPSEEK_API_KEY、OPENAI_API_KEY、DASHSCOPE_API_KEY 等）",
        ),
    )
    root.addWidget(more)
    root.addStretch(1)

    wrap = QtWidgets.QWidget(parent)
    wrap.setObjectName("settingsPanel")
    wrap_lay = QtWidgets.QVBoxLayout(wrap)
    wrap_lay.setContentsMargins(0, 6, 0, 0)
    wrap_lay.setSpacing(0)
    wrap_lay.addWidget(scroll, 1)
    return wrap
